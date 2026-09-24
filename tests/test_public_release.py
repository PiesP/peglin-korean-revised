from __future__ import annotations

import csv
import copy
import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from peglin_l10n.extract import CSV_FIELDS
from peglin_l10n.fingerprints import source_fingerprint
from peglin_l10n.release import build_release_candidate
from peglin_l10n.source_lock import plugin_source_inputs_sha256, read_source_lock
from peglin_l10n.validation import (
    TRANSLATION_FIELDS,
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
        glossary_mismatches = [
            issue.term for issue in issues if issue.code == "GLOSSARY_MISMATCH"
        ]
        self.assertEqual(["Orbs/orb_bonus_desc"], glossary_mismatches)


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
                "<Project><PropertyGroup><Version>0.1.2</Version>"
                "</PropertyGroup></Project>\n"
            ),
            "plugin/Plugin.cs": (
                'namespace Test { [BepInPlugin("id", "name", "0.1.2")] '
                "public class Plugin {} }\n"
            ),
            "plugin/packages.lock.json": "{}\n",
        }
        for path, contents in plugin_sources.items():
            (self.root / path).write_text(contents, encoding="utf-8")
        plugin = self.root / "runtime" / "PeglinKoreanRevised.dll"
        plugin.write_bytes(b"test-plugin")
        terms = self.root / "translation" / "terms" / "general.csv"
        with terms.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(
                stream, fieldnames=TRANSLATION_FIELDS, lineterminator="\n"
            )
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
                "sourceInputsSha256": plugin_source_inputs_sha256(
                    self.root, self.plugin_inputs
                ),
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
            self.plugin_inputs,
        )
        build_release_candidate(
            self.root / "translation" / "terms",
            self.lock_path,
            self.root,
            "abc123",
            second,
            self.plugin_inputs,
        )
        first_files = {path.name: path.read_bytes() for path in first.iterdir()}
        second_files = {path.name: path.read_bytes() for path in second.iterdir()}
        self.assertEqual(first_files, second_files)
        manifest = json.loads(first_files["release-manifest.json"])
        self.assertEqual("abc123", manifest["sourceRevision"])
        self.assertEqual("draft", manifest["status"])
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
                archive.read(
                    "BepInEx/plugins/PeglinKoreanRevised/manifest.json"
                )
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
        self.assertIn("AI 도구의 도움", package_readme)
        self.assertNotIn("Assembly-CSharp.dll SHA-256", package_readme)
        self.assertEqual(
            manifest["runtime"]["pluginVersion"],
            package_manifest["runtime"]["pluginVersion"],
        )

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
                self.plugin_inputs,
            )

    def test_release_rejects_tracked_plugin_drift(self) -> None:
        (self.root / "runtime" / "PeglinKoreanRevised.dll").write_bytes(
            b"changed-plugin"
        )
        with self.assertRaisesRegex(ValueError, "plugin hash"):
            build_release_candidate(
                self.root / "translation" / "terms",
                self.lock_path,
                self.root,
                "abc123",
                self.root / "release",
                self.plugin_inputs,
            )

    def test_repository_source_lock_contains_only_safe_term_metadata(self) -> None:
        repository_root = Path(__file__).resolve().parents[1]
        lock = json.loads(
            (repository_root / "translation" / "source-lock.json").read_text(
                encoding="utf-8"
            )
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
