from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from peglin_l10n import atomic_write, release
from peglin_l10n.cli import main
from peglin_l10n.extract import CSV_FIELDS
from peglin_l10n.fingerprints import source_fingerprint
from peglin_l10n.patching import create_locked_overlay_patch
from peglin_l10n.release import build_release_candidate
from peglin_l10n.source_lock import (
    plugin_source_inputs_sha256,
    read_source_lock,
    validate_runtime_provenance,
)
from peglin_l10n.validation import (
    TRANSLATION_FIELDS,
    protected_tokens,
    read_translation_directory,
    validate,
    validate_locked_translations,
)


class TranslationDirectoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.terms = self.root / "translation" / "terms"
        self.terms.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write_csv(
        self,
        name: str,
        rows: list[dict[str, str]],
        fields: tuple[str, ...] = TRANSLATION_FIELDS,
    ) -> None:
        with (self.terms / name).open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

    def test_rejects_malformed_header(self) -> None:
        self._write_csv(
            "general.csv",
            [{"Term": "Bomb", "Translation": "폭탄"}],
            ("Term", "Translation"),
        )
        with self.assertRaisesRegex(ValueError, "exact columns"):
            read_translation_directory(self.terms)

    def test_rejects_duplicate_keys_across_files(self) -> None:
        row = {
            "Term": "Bomb",
            "Translation": "폭탄",
            "Status": "draft",
            "ReviewedBuildId": "",
            "Comment": "",
        }
        self._write_csv("general.csv", [row])
        self._write_csv("menu.csv", [row])
        with self.assertRaisesRegex(ValueError, "Duplicate term key"):
            read_translation_directory(self.terms)

    def test_reports_missing_key_invalid_fingerprint_and_token_mismatch(self) -> None:
        self._write_csv(
            "general.csv",
            [
                {
                    "Term": "Damage",
                    "Translation": "피해",
                    "Status": "draft",
                    "ReviewedBuildId": "",
                    "Comment": "",
                }
            ],
        )
        lock = {
            "schemaVersion": 1,
            "kind": "peglin-korean-source-lock",
            "game": "Peglin",
            "steamAppId": "1296610",
            "language": "ko",
            "steamBuildId": "1",
            "unityVersion": "2022.3",
            "resourcesAssetsSha256": "a" * 64,
            "assemblyCSharpSha256": "b" * 64,
            "sourceRowCount": 2,
            "translationCount": 2,
            "runtime": {
                "path": "runtime/PeglinKoreanRevised.dll",
                "pluginVersion": "0.1.2",
                "sha256": "c" * 64,
                "sourceInputsSha256": "d" * 64,
            },
            "terms": {
                "Damage": {
                    "category": "General",
                    "file": "general.csv",
                    "sourceFingerprint": "not-a-hash",
                    "protectedTokens": ["{0}"],
                },
                "Missing": {
                    "category": "General",
                    "file": "general.csv",
                    "sourceFingerprint": "f" * 64,
                    "protectedTokens": [],
                },
            },
        }
        summary, issues = validate_locked_translations(self.terms, lock)
        self.assertEqual(3, summary["errors"])
        self.assertEqual(
            {
                "INVALID_LOCKED_FINGERPRINT",
                "MISSING_TRANSLATION_TERM",
                "PROTECTED_TOKEN_MISMATCH",
            },
            {issue.code for issue in issues},
        )

    def test_review_warnings_are_specific_and_do_not_fail_lint(self) -> None:
        cases = [
            (
                "Orbs/healing_slime",
                "orbs.csv",
                "<style=hit>활성화</style>",
            ),
            (
                "Orbs/test_activate_style",
                "orbs.csv",
                "<style=activate>활성화</style>",
            ),
            (
                "Orbs/test_activation_outside_hit",
                "orbs.csv",
                "활성화",
            ),
            (
                "Dialogue System/Conversation/Test/FixedParticle",
                "dialogue-system.csv",
                "[var=orb0]를 포기합니다. [var=orb1]라는 구슬도 봅니다.",
            ),
            (
                "Dialogue System/Conversation/Test/InvariantParticle",
                "dialogue-system.csv",
                "구슬 이름은 [var=orb0]입니다.",
            ),
            (
                "Achievements/NEW_ACHIEVEMENT_16_48_DESC",
                "achievements.csv",
                "페인보우(슬라임)를 처치하세요.",
            ),
            (
                "Challenges/taste_the_painbow_desc",
                "challenges.csv",
                "페인보우 슬라임드롭이 쫓아옵니다.",
            ),
            (
                "Enemies/slime_painbow_lore",
                "enemies.csv",
                "무지개 슬라임드롭의 최종 형태입니다.",
            ),
            (
                "Enemies/slime_painbow_name",
                "enemies.csv",
                "페인보우 슬라임드롭",
            ),
            (
                "Enemies/slime_rainbow_name",
                "enemies.csv",
                "무지개 슬라임드롭",
            ),
            (
                "Enemies/other_enemy_name",
                "enemies.csv",
                "별도의 적 이름",
            ),
            (
                "Relics/mental_mantle_desc",
                "relics.csv",
                '<sprite name="PEG>',
            ),
            (
                "Relics/lifesteal_peg_hit_desc",
                "relics.csv",
                "<sprite name=PEG>",
            ),
            (
                "Relics/valid_sprite_tag",
                "relics.csv",
                '<sprite name="PEG">',
            ),
        ]
        rows_by_file: dict[str, list[dict[str, str]]] = {}
        lock_terms = {}
        for term, filename, translation in cases:
            rows_by_file.setdefault(filename, []).append(
                {
                    "Term": term,
                    "Translation": translation,
                    "Status": "draft",
                    "ReviewedBuildId": "",
                    "Comment": "",
                }
            )
            lock_terms[term] = {
                "category": term.split("/", 1)[0],
                "file": filename,
                "sourceFingerprint": "a" * 64,
                "protectedTokens": protected_tokens(translation),
            }
        for filename, rows in rows_by_file.items():
            self._write_csv(filename, rows)

        lock = {
            "schemaVersion": 1,
            "kind": "peglin-korean-source-lock",
            "game": "Peglin",
            "steamAppId": "1296610",
            "language": "ko",
            "steamBuildId": "1",
            "unityVersion": "2022.3",
            "resourcesAssetsSha256": "a" * 64,
            "assemblyCSharpSha256": "b" * 64,
            "sourceRowCount": len(lock_terms),
            "translationCount": len(lock_terms),
            "runtime": {
                "path": "runtime/PeglinKoreanRevised.dll",
                "pluginVersion": "0.1.2",
                "sha256": "c" * 64,
                "sourceInputsSha256": "d" * 64,
            },
            "terms": lock_terms,
        }
        (self.terms.parent / "source-lock.json").write_text(json.dumps(lock), encoding="utf-8")

        summary, issues = validate_locked_translations(self.terms, lock)
        warnings = [issue for issue in issues if issue.severity == "warning"]
        self.assertEqual(0, summary["errors"])
        self.assertEqual(4, summary["warnings"])
        self.assertEqual(4, len(warnings))
        self.assertEqual(
            {
                "CANONICAL_NAME_DRIFT",
                "FIXED_ORB_NAME_PARTICLE",
                "HIT_STYLE_TERM_COLLISION",
                "MALFORMED_LOCKED_SPRITE_TAG",
            },
            {issue.code for issue in warnings},
        )
        self.assertEqual(
            {
                "Orbs/healing_slime",
                "Dialogue System/Conversation/Test/FixedParticle",
                "Achievements/NEW_ACHIEVEMENT_16_48_DESC",
                "Relics/mental_mantle_desc",
            },
            {issue.term for issue in warnings},
        )

        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main(["lint-overrides", "--translations", str(self.terms)])
        self.assertEqual(0, exit_code)

    def test_source_bound_sprite_tag_repairs_are_narrowly_allowed(self) -> None:
        cases = [
            (
                "Relics/lifesteal_peg_hit_desc",
                "5035aeae4c2eb68887b2bdc7c243933b342b9a979c540dee2b2551ac440cc894",
                "<style=heal2>Steal</style> <style=damage>1 health</style> "
                "from the targeted enemy for every {[INFERNAL_PEGS]} "
                '<sprite name="PEG> <style=activate>Activated</style>.',
                "<style=heal2>흡수</style> <style=damage>체력 1</style> "
                "from the targeted enemy for every {[INFERNAL_PEGS]} "
                '<sprite name="PEG"> <style=activate>활성화</style>.',
            ),
            (
                "Relics/mental_mantle_desc",
                "b20efa66db9d16dc666ea54a606f383891a4cce05ec0897e0a93caa40c5c2a57",
                "Immediately deal <style=damage>1 damage</style> to the targeted "
                'enemy for every {[DAMAGE_ON_PEG_COUNT]} <sprite name="PEG> '
                "<style=activate>Activated</style>.",
                "Immediately deal <style=damage>1 damage</style> to the targeted "
                'enemy for every {[DAMAGE_ON_PEG_COUNT]} <sprite name="PEG"> '
                "<style=activate>활성화</style>.",
            ),
        ]
        rows = []
        lock_terms = {}
        for term, fingerprint, source, translation in cases:
            rows.append(
                {
                    "Term": term,
                    "Translation": translation,
                    "Status": "draft",
                    "ReviewedBuildId": "",
                    "Comment": "",
                }
            )
            lock_terms[term] = {
                "category": "Relics",
                "file": "relics.csv",
                "sourceFingerprint": fingerprint,
                "protectedTokens": protected_tokens(source),
            }
        self._write_csv("relics.csv", rows)
        lock = {"steamBuildId": "22988052", "terms": lock_terms}

        summary, issues = validate_locked_translations(self.terms, lock)
        self.assertEqual(0, summary["errors"])
        self.assertEqual(
            {"Relics/lifesteal_peg_hit_desc", "Relics/mental_mantle_desc"},
            {issue.term for issue in issues if issue.code == "MALFORMED_LOCKED_SPRITE_TAG"},
        )
        self.assertNotIn("PROTECTED_TOKEN_MISMATCH", {issue.code for issue in issues})

        invalid_locks = [
            (copy.deepcopy(lock), {cases[0][0]}),
            (
                copy.deepcopy(lock),
                {cases[0][0], cases[1][0]},
            ),
        ]
        invalid_locks[0][0]["terms"][cases[0][0]]["sourceFingerprint"] = "f" * 64
        invalid_locks[1][0]["steamBuildId"] = "22988053"
        for invalid_lock, expected_terms in invalid_locks:
            with self.subTest(
                build_id=invalid_lock["steamBuildId"],
                first_fingerprint=invalid_lock["terms"][cases[0][0]]["sourceFingerprint"],
            ):
                summary, issues = validate_locked_translations(self.terms, invalid_lock)
                self.assertEqual(len(expected_terms), summary["errors"])
                self.assertEqual(
                    expected_terms,
                    {issue.term for issue in issues if issue.code == "PROTECTED_TOKEN_MISMATCH"},
                )

        mutated_rows = copy.deepcopy(rows)
        mutated_rows[0]["Translation"] = mutated_rows[0]["Translation"].replace(
            '<sprite name="PEG">', '<sprite name="OTHER">'
        )
        self._write_csv("relics.csv", mutated_rows)
        summary, issues = validate_locked_translations(self.terms, lock)
        self.assertEqual(1, summary["errors"])
        self.assertEqual(
            {cases[0][0]},
            {issue.term for issue in issues if issue.code == "PROTECTED_TOKEN_MISMATCH"},
        )

    def test_snapshot_uses_source_bound_sprite_tag_repairs(self) -> None:
        cases = [
            (
                "Relics/lifesteal_peg_hit_desc",
                "<style=heal2>Steal</style> <style=damage>1 health</style> "
                "from the targeted enemy for every {[INFERNAL_PEGS]} "
                '<sprite name="PEG> <style=activate>Activated</style>.',
                "Changed to Activated in v1.2.0 to match its actual functionality",
                "5035aeae4c2eb68887b2bdc7c243933b342b9a979c540dee2b2551ac440cc894",
            ),
            (
                "Relics/mental_mantle_desc",
                "Immediately deal <style=damage>1 damage</style> to the targeted "
                'enemy for every {[DAMAGE_ON_PEG_COUNT]} <sprite name="PEG> '
                "<style=activate>Activated</style>.",
                "",
                "b20efa66db9d16dc666ea54a606f383891a4cce05ec0897e0a93caa40c5c2a57",
            ),
        ]
        source_rows = []
        overrides = {}
        for term, english, dev_notes, fingerprint in cases:
            translation = english.replace('<sprite name="PEG>', '<sprite name="PEG">')
            row = {
                "Term": term,
                "Category": "Relics",
                "English": english,
                "DevNotes": dev_notes,
                "I2Description": "",
                "OfficialKorean": "",
                "RevisedKorean": english,
                "Status": "unreviewed",
                "Comment": "",
            }
            self.assertEqual(fingerprint, source_fingerprint(row))
            source_rows.append(row)
            overrides[term] = {
                "translation": translation,
                "status": "draft",
                "sourceFingerprint": fingerprint,
            }

        terms_path = self.root / "source.csv"
        manifest_path = self.root / "source.json"
        overrides_path = self.root / "overrides.json"

        def check(
            rows: list[dict[str, str]],
            entries: dict[str, dict[str, str]],
            build_id: str = "22988052",
        ) -> set[str]:
            with terms_path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS, lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)
            manifest_path.write_text(json.dumps({"steamBuildId": build_id}), encoding="utf-8")
            overrides_path.write_text(
                json.dumps({"terms": entries, "schemaVersion": 1}), encoding="utf-8"
            )
            _, issues = validate(
                terms_path, overrides_path=overrides_path, source_manifest_path=manifest_path
            )
            return {issue.term for issue in issues if issue.code == "PROTECTED_TOKEN_MISMATCH"}

        self.assertEqual(set(), check(source_rows, overrides))
        repaired_rows = copy.deepcopy(source_rows)
        for row in repaired_rows:
            row["RevisedKorean"] = overrides[row["Term"]]["translation"]
        self.assertEqual(set(), check(repaired_rows, overrides))
        self.assertEqual({case[0] for case in cases}, check(source_rows, overrides, "22988053"))

        changed_rows = copy.deepcopy(source_rows)
        changed_rows[0]["DevNotes"] += "."
        self.assertEqual({cases[0][0]}, check(changed_rows, overrides))

        changed_overrides = copy.deepcopy(overrides)
        changed_overrides[cases[0][0]]["translation"] = changed_overrides[cases[0][0]][
            "translation"
        ].replace('<sprite name="PEG">', '<sprite name="OTHER">')
        self.assertEqual({cases[0][0]}, check(source_rows, changed_overrides))

    def test_glossary_does_not_split_hyphenated_game_names(self) -> None:
        terms_path = self.root / "source.csv"
        source_rows = [
            {
                "Term": "Orbs/bomborb_name",
                "Category": "Orbs",
                "English": "Bob-Orb",
                "DevNotes": "",
                "I2Description": "",
                "OfficialKorean": "터지구",
                "RevisedKorean": "터지구",
                "Status": "unreviewed",
                "Comment": "",
            },
            {
                "Term": "Orbs/portal_name",
                "Category": "Orbs",
                "English": "Jack-Orb-Lantern",
                "DevNotes": "",
                "I2Description": "",
                "OfficialKorean": "할로윈을 즐기라구",
                "RevisedKorean": "할로윈을 즐기라구",
                "Status": "unreviewed",
                "Comment": "",
            },
            {
                "Term": "Orbs/orb_bonus_desc",
                "Category": "Orbs",
                "English": "Gain an Orb",
                "DevNotes": "",
                "I2Description": "",
                "OfficialKorean": "구슬을 얻습니다.",
                "RevisedKorean": "획득합니다.",
                "Status": "unreviewed",
                "Comment": "",
            },
        ]
        with terms_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(source_rows)

        glossary_path = self.root / "glossary.csv"
        with glossary_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(
                stream,
                fieldnames=("Term", "PreferredKorean"),
                lineterminator="\n",
            )
            writer.writeheader()
            writer.writerow({"Term": "orb", "PreferredKorean": "구슬"})

        overrides_path = self.root / "overrides.json"
        overrides_path.write_text(
            json.dumps(
                {
                    "Orbs/bomborb_name": {
                        "translation": "터지구",
                        "status": "draft",
                        "sourceFingerprint": source_fingerprint(source_rows[0]),
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        _, issues = validate(terms_path, glossary_path, overrides_path)
        glossary_mismatches = [issue.term for issue in issues if issue.code == "GLOSSARY_MISMATCH"]
        self.assertEqual(["Orbs/orb_bonus_desc"], glossary_mismatches)


class TrackedReleaseProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        project = Path(__file__).resolve().parents[1]
        self.lock = read_source_lock(project / "translation" / "source-lock.json")
        for relative in (
            "runtime/PeglinKoreanRevised.dll",
            "translation/runtime-retention.json",
            "plugin/NuGet.Config",
            "plugin/PeglinKoreanRevised.csproj",
            "plugin/Plugin.cs",
            "plugin/packages.lock.json",
        ):
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(project / relative, destination)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _receipt(self) -> dict[str, object]:
        return json.loads((self.root / "translation/runtime-retention.json").read_text())

    def _write_receipt(self, receipt: dict[str, object]) -> None:
        (self.root / "translation/runtime-retention.json").write_text(json.dumps(receipt))

    def test_retained_historical_runtime_is_bound_to_exact_current_inputs(self) -> None:
        plugin = validate_runtime_provenance(self.root, self.lock)
        self.assertEqual(self.root / self.lock["runtime"]["path"], plugin)
        receipt = self._receipt()
        self.assertEqual(
            self.lock["runtime"]["sourceInputsSha256"], receipt["historicalSourceInputsSha256"]
        )
        self.assertNotEqual(
            receipt["historicalSourceInputsSha256"], receipt["currentSourceInputsSha256"]
        )

    def test_retained_runtime_rejects_current_input_drift(self) -> None:
        with (self.root / "plugin/PeglinKoreanRevised.csproj").open("a") as stream:
            stream.write("<!-- changed -->\n")
        with self.assertRaisesRegex(ValueError, "receipt does not match locked DLL and inputs"):
            validate_runtime_provenance(self.root, self.lock)

    def test_retained_runtime_rejects_unchanged_source_drift_even_with_updated_digest(self) -> None:
        with (self.root / "plugin/Plugin.cs").open("a") as stream:
            stream.write("// changed\n")
        receipt = self._receipt()
        receipt["currentSourceInputsSha256"] = plugin_source_inputs_sha256(self.root)
        self._write_receipt(receipt)
        with self.assertRaisesRegex(ValueError, "unchanged plugin input drifted"):
            validate_runtime_provenance(self.root, self.lock)

    def test_retained_runtime_rejects_dll_change(self) -> None:
        with (self.root / "runtime/PeglinKoreanRevised.dll").open("ab") as stream:
            stream.write(b"changed")
        with self.assertRaisesRegex(ValueError, "Tracked runtime plugin hash"):
            validate_runtime_provenance(self.root, self.lock)

    def test_retained_runtime_rejects_wrong_historical_inputs_and_bad_revision(self) -> None:
        receipt = self._receipt()
        receipt["historicalChangedInputs"]["plugin/packages.lock.json"] += "\n"
        self._write_receipt(receipt)
        with self.assertRaisesRegex(ValueError, "historical inputs do not match"):
            validate_runtime_provenance(self.root, self.lock)
        receipt = self._receipt()
        receipt["historicalSourceRevision"] = "0" * 40
        self._write_receipt(receipt)
        with self.assertRaisesRegex(ValueError, "receipt does not match locked DLL and inputs"):
            validate_runtime_provenance(self.root, self.lock)

    def test_retained_runtime_rejects_missing_receipt(self) -> None:
        (self.root / "translation/runtime-retention.json").unlink()
        with self.assertRaisesRegex(ValueError, "receipt is missing or invalid"):
            validate_runtime_provenance(self.root, self.lock)


class ReleasePackagingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "translation" / "terms").mkdir(parents=True)
        (self.root / "runtime").mkdir()
        (self.root / "plugin").mkdir()
        (self.root / "LICENSE").write_text("MIT License\n", encoding="utf-8")
        (self.root / "TRANSLATION-NOTICE.txt").write_text(
            "Translation data notice\n", encoding="utf-8"
        )
        self.plugin_inputs = (
            "plugin/NuGet.Config",
            "plugin/PeglinKoreanRevised.csproj",
            "plugin/Plugin.cs",
            "plugin/packages.lock.json",
        )
        plugin_sources = {
            "plugin/NuGet.Config": "<configuration />\n",
            "plugin/PeglinKoreanRevised.csproj": (
                "<Project><PropertyGroup><Version>0.1.2</Version></PropertyGroup></Project>\n"
            ),
            "plugin/Plugin.cs": (
                'namespace Test { [BepInPlugin("id", "name", "0.1.2")] public class Plugin {} }\n'
            ),
            "plugin/packages.lock.json": "{}\n",
        }
        for path, contents in plugin_sources.items():
            (self.root / path).write_text(contents, encoding="utf-8")
        plugin = self.root / "runtime" / "PeglinKoreanRevised.dll"
        plugin.write_bytes(b"test-plugin")
        terms = self.root / "translation" / "terms" / "general.csv"
        with terms.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=TRANSLATION_FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerow(
                {
                    "Term": "Damage",
                    "Translation": "피해 {0}",
                    "Status": "draft",
                    "ReviewedBuildId": "",
                    "Comment": "",
                }
            )
        self.lock = {
            "schemaVersion": 1,
            "kind": "peglin-korean-source-lock",
            "game": "Peglin",
            "steamAppId": "1296610",
            "language": "ko",
            "steamBuildId": "123",
            "unityVersion": "2022.3.62f2",
            "resourcesAssetsSha256": "a" * 64,
            "assemblyCSharpSha256": "b" * 64,
            "sourceRowCount": 1,
            "translationCount": 1,
            "runtime": {
                "path": "runtime/PeglinKoreanRevised.dll",
                "pluginVersion": "0.1.2",
                "sha256": hashlib.sha256(plugin.read_bytes()).hexdigest(),
                "sourceInputsSha256": plugin_source_inputs_sha256(self.root, self.plugin_inputs),
            },
            "terms": {
                "Damage": {
                    "category": "General",
                    "file": "general.csv",
                    "sourceFingerprint": "e" * 64,
                    "protectedTokens": ["{0}"],
                }
            },
        }
        self.lock_path = self.root / "translation" / "source-lock.json"
        self._write_lock()

    def _write_lock(self) -> None:
        self.lock_path.write_text(
            json.dumps(self.lock, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_release_outputs_are_deterministic_and_revision_bound(self) -> None:
        first = self.root / "first"
        second = self.root / "second"
        build_release_candidate(
            self.root / "translation" / "terms",
            self.lock_path,
            self.root,
            "abc123",
            first,
            release_tag="peglin-ko-v1.0.0-rc.1",
            plugin_source_inputs=self.plugin_inputs,
        )
        build_release_candidate(
            self.root / "translation" / "terms",
            self.lock_path,
            self.root,
            "abc123",
            second,
            release_tag="peglin-ko-v1.0.0-rc.1",
            plugin_source_inputs=self.plugin_inputs,
        )
        first_files = {path.name: path.read_bytes() for path in first.iterdir()}
        second_files = {path.name: path.read_bytes() for path in second.iterdir()}
        self.assertEqual(first_files, second_files)
        for path in first.iterdir():
            self.assertEqual(0o644, path.stat().st_mode & 0o777, path.name)
        overlay_name = next(
            name
            for name in first_files
            if name.endswith(".json") and name != "release-manifest.json"
        )
        overlay = json.loads(first_files[overlay_name])
        self.assertEqual(
            (json.dumps(overlay, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
            first_files[overlay_name],
        )
        manifest = json.loads(first_files["release-manifest.json"])
        self.assertEqual(
            (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
            first_files["release-manifest.json"],
        )
        self.assertEqual(2, manifest["schemaVersion"])
        self.assertEqual("abc123", manifest["sourceRevision"])
        self.assertEqual("peglin-ko-v1.0.0-rc.1", manifest["releaseTag"])
        self.assertTrue(manifest["prerelease"])
        self.assertEqual("draft", manifest["status"])
        self.assertIn(
            "peglin-ko-v1.0.0-rc.1",
            first_files["release-notes.md"].decode("utf-8"),
        )
        release_notes = first_files["release-notes.md"].decode("utf-8")
        self.assertIn("실제 플레이로 확인되지 않은 번역", release_notes)
        self.assertIn("대상 Steam 빌드: `123`", release_notes)
        self.assertIn("issues/new?template=translation-suggestion.yml", release_notes)
        self.assertIn("issues/new?template=patch-problem.yml", release_notes)
        self.assertIn("releases/tag/peglin-ko-v1.0.0-rc.1", release_notes)
        self.assertIn("PeglinKoreanRevised-*.zip", release_notes)
        self.assertIn(
            "blob/peglin-ko-v1.0.0-rc.1/README.md",
            release_notes,
        )
        self.assertEqual(
            hashlib.sha256(first_files["LICENSE"]).hexdigest(),
            manifest["artifacts"]["LICENSE"],
        )
        self.assertEqual(
            hashlib.sha256(first_files["TRANSLATION-NOTICE.txt"]).hexdigest(),
            manifest["artifacts"]["TRANSLATION-NOTICE.txt"],
        )
        candidate_name = next(name for name in first_files if name.endswith(".zip"))
        with zipfile.ZipFile(first / candidate_name) as archive:
            package_manifest = json.loads(
                archive.read("BepInEx/plugins/PeglinKoreanRevised/manifest.json")
            )
            package_readme = archive.read("README.md").decode("utf-8")
            self.assertEqual(first_files["LICENSE"], archive.read("LICENSE"))
            self.assertEqual(
                first_files["TRANSLATION-NOTICE.txt"],
                archive.read("TRANSLATION-NOTICE.txt"),
            )
        self.assertIn("Peglin.exe", package_readme)
        self.assertIn("Type = MonoBehaviour", package_readme)
        self.assertIn("BepInEx/plugins/PeglinKoreanRevised", package_readme)
        self.assertIn("수동 설치 후 폴더 구조", package_readme)
        self.assertIn("├── Peglin.exe", package_readme)
        self.assertIn("├── README.md", package_readme)
        self.assertIn("└── TRANSLATION-NOTICE.txt", package_readme)
        self.assertIn("번역 상태: 초안", package_readme)
        self.assertIn("Steam Build ID `123`", package_readme)
        self.assertIn("실제 플레이에서 발견한 사용자 제보", package_readme)
        self.assertIn("issues/new?template=translation-suggestion.yml", package_readme)
        self.assertIn("AI 도구의 도움", package_readme)
        self.assertIn("BepInEx/LogOutput.log", package_readme)
        self.assertIn("실행에 사용한 Peglin 프로필", package_readme)
        self.assertIn("README.md#적용-상태-확인과-문제-해결", package_readme)
        self.assertIn("`Loaded`는 파일을 읽었다는 뜻이며 적용 완료가 아닙니다", package_readme)
        self.assertNotIn("Assembly-CSharp.dll SHA-256", package_readme)
        self.assertEqual(
            manifest["runtime"]["pluginVersion"],
            package_manifest["runtime"]["pluginVersion"],
        )

    def test_optional_footprint_reconciles_zip_and_rejects_source_drift(self) -> None:
        (self.root / "pyproject.toml").write_text("[project]\nname = 'fixture'\n", encoding="utf-8")
        (self.root / "uv.lock").write_text("version = 1\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.name", "Fixture"], check=True)
        subprocess.run(
            ["git", "-C", str(self.root), "config", "user.email", "fixture@example.invalid"],
            check=True,
        )
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-qm", "fixture"], check=True)
        source_sha = subprocess.run(
            ["git", "-C", str(self.root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        output_dir = self.root / "reported-release"
        report_path = self.root / "footprint.json"
        build_release_candidate(
            self.root / "translation" / "terms",
            self.lock_path,
            self.root,
            source_sha,
            output_dir,
            release_tag="peglin-ko-v1.0.0-rc.1",
            plugin_source_inputs=self.plugin_inputs,
            footprint_report=report_path,
        )
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(source_sha, report["source_revision"])
        self.assertEqual("current locked plugin inputs", report["runtime_provenance"]["origin"])
        self.assertEqual(
            report["runtime_provenance"]["historical_source_inputs_sha256"],
            report["runtime_provenance"]["current_source_inputs_sha256"],
        )
        self.assertEqual(7, len(list(output_dir.iterdir())))
        self.assertEqual(6, len(report["install_zip"]["members"]))
        zip_path = next(output_dir.glob("*.zip"))
        self.assertEqual(
            hashlib.sha256(zip_path.read_bytes()).hexdigest(), report["install_zip"]["sha256"]
        )
        self.assertEqual(zip_path.stat().st_size, report["install_zip"]["bytes"])
        self.assertEqual(
            report["install_zip"]["bytes"],
            report["install_zip"]["member_compressed_bytes"]
            + report["install_zip"]["container_overhead_bytes"],
        )
        self.assertGreater(report["install_zip"]["container_overhead_bytes"], 0)
        with zipfile.ZipFile(zip_path) as archive:
            for row in report["install_zip"]["members"]:
                info = archive.getinfo(row["name"])
                self.assertEqual(info.file_size, row["uncompressed_bytes"])
                self.assertEqual(info.compress_size, row["compressed_bytes"])
                self.assertEqual(hashlib.sha256(archive.read(info)).hexdigest(), row["sha256"])
        self.assertEqual(
            report["standalone_overlay"]["sha256"],
            next(
                row["sha256"]
                for row in report["install_zip"]["members"]
                if row["name"].endswith("/overlay.json")
            ),
        )
        with self.assertRaisesRegex(ValueError, "already exists"):
            build_release_candidate(
                self.root / "translation" / "terms",
                self.lock_path,
                self.root,
                source_sha,
                output_dir,
                release_tag="peglin-ko-v1.0.0-rc.1",
                plugin_source_inputs=self.plugin_inputs,
                footprint_report=report_path,
            )
        (self.root / "LICENSE").write_text("changed license\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "exact clean checked-out source"):
            build_release_candidate(
                self.root / "translation" / "terms",
                self.lock_path,
                self.root,
                source_sha,
                self.root / "dirty-release",
                release_tag="peglin-ko-v1.0.0-rc.1",
                plugin_source_inputs=self.plugin_inputs,
                footprint_report=self.root / "dirty-report.json",
            )

    def test_release_reuse_rejects_before_changing_completed_generation(self) -> None:
        output_dir = self.root / "release"
        build_release_candidate(
            self.root / "translation" / "terms",
            self.lock_path,
            self.root,
            "old123",
            output_dir,
            release_tag="peglin-ko-v1.0.0-rc.1",
            plugin_source_inputs=self.plugin_inputs,
        )
        original_files = {path.name: path.read_bytes() for path in output_dir.iterdir()}
        csv_path = self.root / "translation" / "terms" / "general.csv"
        csv_path.write_text(
            csv_path.read_text(encoding="utf-8").replace("피해 {0}", "공격 {0}"), encoding="utf-8"
        )
        license_path = output_dir / "LICENSE"
        original_replace = os.replace

        def fail_license_replace(source: Path, destination: Path) -> None:
            if destination == license_path:
                raise OSError("injected license replacement failure")
            original_replace(source, destination)

        with patch.object(atomic_write.os, "replace", side_effect=fail_license_replace):
            with self.assertRaisesRegex(FileExistsError, "already exists"):
                build_release_candidate(
                    self.root / "translation" / "terms",
                    self.lock_path,
                    self.root,
                    "new456",
                    output_dir,
                    release_tag="peglin-ko-v1.0.0-rc.1",
                    plugin_source_inputs=self.plugin_inputs,
                )
        self.assertEqual(
            original_files, {path.name: path.read_bytes() for path in output_dir.iterdir()}
        )

    def test_release_failed_writes_leave_no_completion_marker_and_retry_uses_new_path(self) -> None:
        original_replace = os.replace
        for failed_name in ("LICENSE", "SHA256SUMS.txt"):
            with self.subTest(failed_name=failed_name):
                output_dir = self.root / f"failed-{failed_name}"

                def fail_selected_replace(source: Path, destination: Path) -> None:
                    if destination == output_dir / failed_name:
                        raise OSError("injected release write failure")
                    original_replace(source, destination)

                with patch.object(atomic_write.os, "replace", side_effect=fail_selected_replace):
                    with self.assertRaisesRegex(OSError, "injected release write failure"):
                        build_release_candidate(
                            self.root / "translation" / "terms",
                            self.lock_path,
                            self.root,
                            "a" * 40,
                            output_dir,
                            release_tag="peglin-ko-v1.0.0-rc.1",
                            plugin_source_inputs=self.plugin_inputs,
                        )
                self.assertTrue(output_dir.is_dir())
                self.assertFalse((output_dir / "SHA256SUMS.txt").exists())
                self.assertEqual([], list(output_dir.glob(".*.tmp")))
                if failed_name == "LICENSE":
                    self.assertFalse((output_dir / "release-manifest.json").exists())
                else:
                    self.assertTrue((output_dir / "release-manifest.json").exists())
                verifier = (
                    Path(__file__).resolve().parents[1]
                    / ".github/scripts/verify_release_artifacts.py"
                )
                environment = os.environ | {
                    "RELEASE_DIR": str(output_dir),
                    "SOURCE_SHA": "a" * 40,
                    "RELEASE_TAG": "peglin-ko-v1.0.0-rc.1",
                    "GITHUB_OUTPUT": str(self.root / f"verification-output-{failed_name}"),
                }
                rejected = subprocess.run(
                    [os.sys.executable, str(verifier)],
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(0, rejected.returncode)
                self.assertFalse((self.root / f"verification-output-{failed_name}").exists())
                with self.assertRaisesRegex(FileExistsError, "already exists"):
                    build_release_candidate(
                        self.root / "translation" / "terms",
                        self.lock_path,
                        self.root,
                        "a" * 40,
                        output_dir,
                        release_tag="peglin-ko-v1.0.0-rc.1",
                        plugin_source_inputs=self.plugin_inputs,
                    )
                retry = self.root / f"retry-{failed_name}"
                build_release_candidate(
                    self.root / "translation" / "terms",
                    self.lock_path,
                    self.root,
                    "a" * 40,
                    retry,
                    release_tag="peglin-ko-v1.0.0-rc.1",
                    plugin_source_inputs=self.plugin_inputs,
                )
                self.assertEqual(7, len(list(retry.iterdir())))
                self.assertTrue((retry / "SHA256SUMS.txt").is_file())
                accepted = subprocess.run(
                    [os.sys.executable, str(verifier)],
                    env=environment | {"RELEASE_DIR": str(retry)},
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(0, accepted.returncode, accepted.stderr)

    def test_release_rejects_invalid_status_and_destination_race_before_writing(self) -> None:
        output_dir = self.root / "release"
        with self.assertRaisesRegex(ValueError, "Draft translations require"):
            build_release_candidate(
                self.root / "translation" / "terms",
                self.lock_path,
                self.root,
                "a" * 40,
                output_dir,
                release_tag="peglin-ko-v1.0.0",
                plugin_source_inputs=self.plugin_inputs,
            )
        self.assertFalse(output_dir.exists())

        original_read = release.read_translation_directory

        def race_after_preflight(path: Path) -> dict[str, dict[str, str]]:
            output_dir.mkdir()
            (output_dir / "other-owner.txt").write_text("preserve", encoding="utf-8")
            return original_read(path)

        with patch.object(release, "read_translation_directory", side_effect=race_after_preflight):
            with self.assertRaises(FileExistsError):
                build_release_candidate(
                    self.root / "translation" / "terms",
                    self.lock_path,
                    self.root,
                    "a" * 40,
                    output_dir,
                    release_tag="peglin-ko-v1.0.0-rc.1",
                    plugin_source_inputs=self.plugin_inputs,
                )
        self.assertEqual("preserve", (output_dir / "other-owner.txt").read_text(encoding="utf-8"))

    def test_locked_overlay_fsync_failure_keeps_existing_destination(self) -> None:
        overlay_path = self.root / "output" / "overlay.json"
        overlay_path.parent.mkdir()
        overlay_path.write_bytes(b"previous overlay")
        with patch.object(
            atomic_write.os, "fsync", side_effect=OSError("injected overlay sync failure")
        ):
            with self.assertRaisesRegex(OSError, "injected overlay sync failure"):
                create_locked_overlay_patch(
                    self.root / "translation" / "terms", self.lock, overlay_path
                )
        self.assertEqual(b"previous overlay", overlay_path.read_bytes())
        self.assertEqual([], list(overlay_path.parent.glob(".overlay.json.*.tmp")))

    def test_source_lock_rejects_unregistered_root_field(self) -> None:
        self.lock["sourceTextDump"] = "proprietary source text"
        self._write_lock()
        with self.assertRaisesRegex(ValueError, "root fields"):
            read_source_lock(self.lock_path)

    def test_source_lock_rejects_category_and_file_mismatch(self) -> None:
        for field, value, expected_message in (
            ("category", "Menu", "category"),
            ("file", "menu.csv", "CSV file"),
        ):
            with self.subTest(field=field):
                changed = copy.deepcopy(self.lock)
                changed["terms"]["Damage"][field] = value
                self.lock_path.write_text(
                    json.dumps(changed, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(ValueError, expected_message):
                    read_source_lock(self.lock_path)

    def test_release_rejects_plugin_version_mismatch(self) -> None:
        self.lock["runtime"]["pluginVersion"] = "0.1.3"
        self._write_lock()
        with self.assertRaisesRegex(ValueError, "pluginVersion"):
            build_release_candidate(
                self.root / "translation" / "terms",
                self.lock_path,
                self.root,
                "abc123",
                self.root / "release",
                release_tag="peglin-ko-v1.0.0-rc.1",
                plugin_source_inputs=self.plugin_inputs,
            )

    def test_release_rejects_tracked_plugin_drift(self) -> None:
        (self.root / "runtime" / "PeglinKoreanRevised.dll").write_bytes(b"changed-plugin")
        with self.assertRaisesRegex(ValueError, "plugin hash"):
            build_release_candidate(
                self.root / "translation" / "terms",
                self.lock_path,
                self.root,
                "abc123",
                self.root / "release",
                release_tag="peglin-ko-v1.0.0-rc.1",
                plugin_source_inputs=self.plugin_inputs,
            )

    def test_repository_source_lock_contains_only_safe_term_metadata(self) -> None:
        repository_root = Path(__file__).resolve().parents[1]
        lock = json.loads(
            (repository_root / "translation" / "source-lock.json").read_text(encoding="utf-8")
        )
        self.assertEqual(1899, len(lock["terms"]))
        for metadata in lock["terms"].values():
            self.assertEqual(
                {"category", "file", "sourceFingerprint", "protectedTokens"},
                set(metadata),
            )
        serialized = json.dumps(lock, ensure_ascii=False)
        for forbidden in ("English", "OfficialKorean", "DevNotes", "I2Description", "assetPath"):
            self.assertNotIn(f'"{forbidden}"', serialized)


if __name__ == "__main__":
    unittest.main()
