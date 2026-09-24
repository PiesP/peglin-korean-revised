from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from peglin_l10n.release import build_release_candidate
from peglin_l10n.source_lock import plugin_source_inputs_sha256
from peglin_l10n.validation import (
    TRANSLATION_FIELDS,
    read_translation_directory,
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


class ReleasePackagingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "translation" / "terms").mkdir(parents=True)
        (self.root / "runtime").mkdir()
        (self.root / "plugin").mkdir()
        self.plugin_inputs = (
            "plugin/NuGet.Config",
            "plugin/PeglinKoreanRevised.csproj",
            "plugin/Plugin.cs",
            "plugin/packages.lock.json",
        )
        for path in self.plugin_inputs:
            (self.root / path).write_text(path + "\n", encoding="utf-8")
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
        lock = {
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
        self.lock_path.write_text(
            json.dumps(lock, ensure_ascii=False) + "\n", encoding="utf-8"
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
