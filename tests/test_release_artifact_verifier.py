"""Synthetic release fixtures exercised through the publication verifier CLI."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/release-translation.yml"
SCRIPT = ROOT / ".github/scripts/verify_release_artifacts.py"
SOURCE_SHA = "a" * 40
PLUGIN = "BepInEx/plugins/PeglinKoreanRevised/PeglinKoreanRevised.dll"
OVERLAY = "BepInEx/plugins/PeglinKoreanRevised/overlay.json"
PACKAGE = "BepInEx/plugins/PeglinKoreanRevised/manifest.json"
ARCHIVE = "PeglinKoreanRevised-123-bbbbbbbb.zip"
STANDALONE = "peglin-ko-123-bbbbbbbb.json"


def encoded(document: dict) -> bytes:
    return (json.dumps(document, ensure_ascii=False) + "\n").encode("utf-8")


def digest(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()


def archive_bytes(members: dict[str, bytes]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, contents in members.items():
            archive.writestr(name, contents)
    return stream.getvalue()


class ReleaseFixture:
    def __init__(self, root: Path, *, prerelease: bool) -> None:
        self.root = root
        self.tag = "peglin-ko-v1.0.0-rc.1" if prerelease else "peglin-ko-v1.0.0"
        status = "draft" if prerelease else "approved"
        source = {
            "steamAppId": "1296610",
            "steamBuildId": "123",
            "unityVersion": "2022.3.62f2",
            "assetSha256": "b" * 64,
        }
        self.overlay = {
            "kind": "peglin-korean-overlay", "game": "Peglin", "language": "ko",
            "status": status, "source": source, "terms": {"Test": "테스트"},
        }
        self.plugin_bytes = b"synthetic plugin fixture"
        self.package = {
            "kind": "peglin-korean-client-candidate", "game": "Peglin",
            "steamAppId": "1296610", "language": "ko", "status": status,
            "translationCount": 1, "source": source,
            "runtime": {"pluginVersion": "0.1.2", "assemblyCSharpSha256": "c" * 64},
            "files": {PLUGIN: digest(self.plugin_bytes), OVERLAY: digest(encoded(self.overlay))},
        }
        self.members = {
            PLUGIN: self.plugin_bytes, OVERLAY: encoded(self.overlay),
            PACKAGE: encoded(self.package), "README.md": b"Synthetic install notice\n",
            "LICENSE": b"Synthetic license\n",
            "TRANSLATION-NOTICE.txt": b"Synthetic translation notice\n",
        }
        self.manifest = {
            "schemaVersion": 2, "kind": "peglin-korean-release-provenance",
            "game": "Peglin", "steamAppId": "1296610", "language": "ko",
            "sourceRevision": SOURCE_SHA, "releaseTag": self.tag,
            "status": status, "prerelease": prerelease, "translationCount": 1,
            "source": {
                "steamBuildId": "123", "unityVersion": "2022.3.62f2",
                "resourcesAssetsSha256": "b" * 64,
                "assemblyCSharpSha256": "c" * 64,
            },
            "runtime": {"pluginVersion": "0.1.2", "sha256": digest(self.plugin_bytes)},
            "artifacts": {},
        }
        self.seal()

    def seal(self) -> None:
        self.members[OVERLAY] = encoded(self.overlay)
        self.members[PACKAGE] = encoded(self.package)
        files = {
            STANDALONE: encoded(self.overlay), ARCHIVE: archive_bytes(self.members),
            "release-notes.md": b"Synthetic release notes\n",
            "LICENSE": self.members["LICENSE"],
            "TRANSLATION-NOTICE.txt": self.members["TRANSLATION-NOTICE.txt"],
        }
        self.manifest["artifacts"] = {name: digest(contents) for name, contents in files.items()}
        files["release-manifest.json"] = encoded(self.manifest)
        checksums = "".join(
            f"{digest(contents)}  {name}\n" for name, contents in sorted(files.items())
        )
        files["SHA256SUMS.txt"] = checksums.encode("ascii")
        for name, contents in files.items():
            (self.root / name).write_bytes(contents)


def workflow_verifier() -> str | None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    if "          python3 - <<'PY'\n" not in workflow:
        return None
    block = workflow.split("          python3 - <<'PY'\n", 1)[1].split("          PY\n", 1)[0]
    return "\n".join(line[10:] for line in block.splitlines()) + "\n"


class ReleaseArtifactVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.output = self.root / "github-output"
        self.fixture = ReleaseFixture(self.root, prerelease=True)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_verifier(self, *, source: str = SOURCE_SHA, tag: str | None = None,
                     workflow: bool = False) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.update({
            "RELEASE_DIR": str(self.root), "SOURCE_SHA": source,
            "RELEASE_TAG": tag or self.fixture.tag, "GITHUB_OUTPUT": str(self.output),
        })
        inline = workflow_verifier() if workflow else None
        return subprocess.run(
            [sys.executable, "-c", inline] if inline is not None else [sys.executable, str(SCRIPT)],
            text=True, capture_output=True, env=env, check=False,
        )

    def assert_rejected(self, expected: str) -> None:
        result = self.run_verifier()
        self.assertNotEqual(0, result.returncode)
        self.assertIn(expected, result.stderr)
        self.assertFalse(self.output.exists(), "invalid artifact wrote success outputs")

    def test_accepts_synthetic_rc_and_stable(self) -> None:
        for prerelease in (True, False):
            with self.subTest(prerelease=prerelease):
                self.fixture = ReleaseFixture(self.root, prerelease=prerelease)
                result = self.run_verifier()
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(
                    f"prerelease={'true' if prerelease else 'false'}\n"
                    f"tag={self.fixture.tag}\noverlay={STANDALONE}\n",
                    self.output.read_text(encoding="utf-8"),
                )
                self.output.unlink()

    def test_extracted_cli_matches_actual_workflow_bound_verifier(self) -> None:
        if workflow_verifier() is None:
            self.skipTest("the workflow now calls the extracted verifier")
        for prerelease in (True, False):
            with self.subTest(prerelease=prerelease):
                self.fixture = ReleaseFixture(self.root, prerelease=prerelease)
                baseline = self.run_verifier(workflow=True)
                self.assertEqual(0, baseline.returncode, baseline.stderr)
                baseline_output = self.output.read_bytes()
                self.output.unlink()
                extracted = self.run_verifier()
                self.assertEqual(0, extracted.returncode, extracted.stderr)
                self.assertEqual(baseline_output, self.output.read_bytes())
                self.output.unlink()

    def test_rejects_identity_and_manifest_mismatches(self) -> None:
        cases = (
            (lambda: self.run_verifier(source="short"), "full Git SHA"),
            (lambda: self.run_verifier(tag="bad-tag"), "reserved version format"),
        )
        for invoke, message in cases:
            with self.subTest(message=message):
                result = invoke()
                self.assertNotEqual(0, result.returncode)
                self.assertIn(message, result.stderr)
                self.assertFalse(self.output.exists())
        changes = (
            ("sourceRevision", "d" * 40, "verified source commit"),
            ("releaseTag", "peglin-ko-v9.9.9", "administrator-selected tag"),
            ("status", "unknown", "translation status is invalid"),
            ("prerelease", False, "prerelease flag"),
            ("schemaVersion", 1, "manifest kind"),
            ("kind", "unexpected", "manifest kind"),
            ("translationCount", 2, "Translation counts disagree"),
        )
        for field, value, message in changes:
            with self.subTest(field=field):
                self.fixture = ReleaseFixture(self.root, prerelease=True)
                self.fixture.manifest[field] = value
                self.fixture.seal()
                self.assert_rejected(message)

    def test_rejects_malformed_json_and_cross_manifest_metadata(self) -> None:
        (self.root / "release-manifest.json").write_bytes(b"{")
        self._reseal_checksums()
        self.assert_rejected("Expecting property name")
        cases = (
            (lambda f: f.overlay.__setitem__("status", "approved"), "Translation status disagrees"),
            (lambda f: f.overlay.__setitem__("game", "Other"), "Game, language, or source metadata"),
            (lambda f: f.overlay["source"].__setitem__("steamBuildId", "changed"), "Peglin source metadata"),
            (lambda f: f.manifest["runtime"].__setitem__("sha256", "f" * 64), "Runtime metadata"),
            (lambda f: f.manifest["artifacts"].pop("LICENSE"), "artifact inventory"),
        )
        for change, message in cases:
            with self.subTest(message=message):
                self.fixture = ReleaseFixture(self.root, prerelease=True)
                change(self.fixture)
                if message == "artifact inventory":
                    (self.root / "release-manifest.json").write_bytes(encoded(self.fixture.manifest))
                    self._reseal_checksums()
                else:
                    self.fixture.package["files"][OVERLAY] = digest(encoded(self.fixture.overlay))
                    self.fixture.seal()
                self.assert_rejected(message)

    def test_rejects_file_inventory_and_checksum_failures(self) -> None:
        (self.root / "LICENSE").unlink()
        self.assert_rejected("missing required files")
        self.fixture.seal()
        (self.root / "extra.txt").write_text("extra", encoding="utf-8")
        self.assert_rejected("checksum inventory")
        (self.root / "extra.txt").unlink()
        (self.root / "LICENSE").write_bytes(b"corrupt")
        self.assert_rejected("Checksum mismatch")
        self.fixture.seal()
        sums = self.root / "SHA256SUMS.txt"
        sums.write_bytes(sums.read_bytes() + sums.read_bytes().splitlines(keepends=True)[0])
        self.assert_rejected("invalid or duplicate entry")
        self.fixture.seal()
        sums.write_bytes(b"not a checksum\n")
        self.assert_rejected("invalid or duplicate entry")
        self.fixture.seal()
        sums.write_bytes(sums.read_bytes().replace(b"  LICENSE\n", b"  absent\n"))
        self.assert_rejected("required release files")
        self.fixture.seal()
        (self.root / "subdir").mkdir()
        self.assert_rejected("unexpected directory or symlink")

    def test_rejects_symlink_if_supported(self) -> None:
        target = self.root / "LICENSE"
        link = self.root / "unexpected-link"
        try:
            link.symlink_to(target)
        except (NotImplementedError, OSError):
            self.skipTest("symlinks unavailable")
        self.assert_rejected("unexpected directory or symlink")

    def test_rejects_zip_and_cross_file_mismatches(self) -> None:
        changes = (
            (lambda f: f.members.update({"unexpected": b"x"}), "unexpected or duplicate members"),
            (lambda f: f.members.__setitem__(OVERLAY, b"different"), "differ"),
            (lambda f: f.members.__setitem__("LICENSE", b"different"), "MIT License differs"),
            (lambda f: f.members.__setitem__("TRANSLATION-NOTICE.txt", b"different"), "translation notice differs"),
            (lambda f: f.package.__setitem__("translationCount", 2), "Translation counts disagree"),
            (lambda f: f.package["runtime"].__setitem__("pluginVersion", "changed"), "Runtime metadata disagrees"),
            (lambda f: f.package["files"].__setitem__(PLUGIN, "f" * 64), "manifest hash mismatch"),
        )
        for change, message in changes:
            with self.subTest(message=message):
                self.fixture = ReleaseFixture(self.root, prerelease=True)
                change(self.fixture)
                # Preserve changed archive members rather than normalizing them.
                if message not in {"differ", "MIT License differs", "translation notice differs"}:
                    self.fixture.members[PACKAGE] = encoded(self.fixture.package)
                archive = archive_bytes(self.fixture.members)
                (self.root / ARCHIVE).write_bytes(archive)
                self.fixture.manifest["artifacts"][ARCHIVE] = digest(archive)
                (self.root / "release-manifest.json").write_bytes(encoded(self.fixture.manifest))
                self._reseal_checksums()
                self.assert_rejected(message)

    def test_rejects_duplicate_truncated_and_crc_damaged_zip(self) -> None:
        archive = self.root / ARCHIVE
        with io.BytesIO() as stream:
            with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as writer:
                for name, contents in self.fixture.members.items():
                    writer.writestr(name, contents)
                with self.assertWarns(UserWarning):
                    writer.writestr(PLUGIN, self.fixture.plugin_bytes)
            self._replace_archive(stream.getvalue())
        self.assert_rejected("unexpected or duplicate members")

        self.fixture.seal()
        self._replace_archive(archive.read_bytes()[:-10])
        self.assert_rejected("File is not a zip file")

        self.fixture.seal()
        broken = bytearray(archive.read_bytes())
        offset = broken.index(self.fixture.plugin_bytes)
        broken[offset] ^= 1
        self._replace_archive(bytes(broken))
        self.assert_rejected("CRC")

    def test_missing_artifact_or_output_path_fails_closed(self) -> None:
        (self.root / "release-manifest.json").unlink()
        self.assert_rejected("missing required files")
        self.fixture.seal()
        self.output = self.root / "missing-parent" / "github-output"
        result = self.run_verifier()
        self.assertNotEqual(0, result.returncode)
        self.assertFalse(self.output.exists())

    def test_import_does_not_invoke_process_or_write_outputs(self) -> None:
        spec = importlib.util.spec_from_file_location("verify_release_artifacts", SCRIPT)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        with patch.object(subprocess, "run", side_effect=AssertionError("import invoked a process")):
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        self.assertFalse(self.output.exists())

    def _replace_archive(self, contents: bytes) -> None:
        (self.root / ARCHIVE).write_bytes(contents)
        self.fixture.manifest["artifacts"][ARCHIVE] = digest(contents)
        (self.root / "release-manifest.json").write_bytes(encoded(self.fixture.manifest))
        self._reseal_checksums()

    def _reseal_checksums(self) -> None:
        files = (path for path in self.root.iterdir() if path.is_file() and path.name != "SHA256SUMS.txt")
        (self.root / "SHA256SUMS.txt").write_text(
            "".join(f"{digest(path.read_bytes())}  {path.name}\n" for path in sorted(files)),
            encoding="ascii",
        )


if __name__ == "__main__":
    unittest.main()
