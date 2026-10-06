"""The release adapter has no live GitHub calls in these tests."""

from __future__ import annotations

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_release_artifact_verifier import ARCHIVE, ReleaseFixture, SOURCE_SHA, STANDALONE


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github/scripts/publish_release.py"
SPEC = importlib.util.spec_from_file_location("publish_release", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Could not load release adapter.")
with patch.object(subprocess, "run", side_effect=AssertionError("import invoked a process")):
    publisher = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(publisher)


class ReleasePublisherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.fixture = ReleaseFixture(self.root, prerelease=True)
        self.calls: list[list[str]] = []
        self.tag_object = "d" * 40

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_gh(self, argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        self.calls.append(argv)
        if argv[1] == "api":
            self.assertEqual({"check": True, "capture_output": True, "text": True}, kwargs)
            return subprocess.CompletedProcess(argv, 0, self.tag_object + "\n", "")
        self.assertEqual({"check": True}, kwargs)
        return subprocess.CompletedProcess(argv, 0)

    def publish(self, **changes: object) -> None:
        params = {
            "root": self.root, "repository": "PiesP/peglin-korean-revised",
            "source_sha": SOURCE_SHA, "tag": self.fixture.tag,
            "tag_object_sha": "d" * 40, "prerelease": True,
            "overlay_name": STANDALONE, "run": self.run_gh,
        }
        params.update(changes)
        publisher.publish_release(**params)

    def test_exact_release_arguments_and_rc_flag(self) -> None:
        self.publish()
        self.assertEqual(
            ["gh", "api", f"repos/PiesP/peglin-korean-revised/git/ref/tags/{self.fixture.tag}",
             "--jq", ".object.sha"],
            self.calls[0],
        )
        self.assertEqual(
            ["gh", "release", "create", self.fixture.tag, "--verify-tag",
             "--target", SOURCE_SHA, "--title", "Peglin Korean Revised v1.0.0-rc.1",
             "--notes-file", str(self.root / "release-notes.md"), "--prerelease",
             "--repo", "PiesP/peglin-korean-revised", str(self.root / STANDALONE),
             str(self.root / ARCHIVE), str(self.root / "LICENSE"),
             str(self.root / "TRANSLATION-NOTICE.txt"),
             str(self.root / "release-notes.md"),
             str(self.root / "release-manifest.json"),
             str(self.root / "SHA256SUMS.txt")],
            self.calls[1],
        )

    def test_stable_release_omits_prerelease_flag(self) -> None:
        self.fixture = ReleaseFixture(self.root, prerelease=False)
        self.publish(prerelease=False)
        self.assertEqual(2, len(self.calls))
        self.assertNotIn("--prerelease", self.calls[1])
        self.assertIn("Peglin Korean Revised v1.0.0", self.calls[1])

    def test_changed_annotated_tag_object_blocks_release(self) -> None:
        # The same peeled source commit is still selected; only the tag object moved.
        self.tag_object = "e" * 40
        with self.assertRaisesRegex(ValueError, "protected release tag changed"):
            self.publish()
        self.assertEqual(1, len(self.calls))

    def test_invalid_inputs_stop_before_gh(self) -> None:
        invalid = (
            {"source_sha": "short"}, {"tag": "other-tag"},
            {"prerelease": False}, {"tag_object_sha": "invalid"},
            {"overlay_name": "../outside.json"},
        )
        for changes in invalid:
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    self.publish(**changes)
                self.assertEqual([], self.calls)
        (self.root / ARCHIVE).unlink()
        with self.assertRaisesRegex(ValueError, "one verified install archive"):
            self.publish()
        self.assertEqual([], self.calls)

    def test_api_and_release_errors_are_not_retried(self) -> None:
        def api_failure(argv: list[str], **kwargs: object) -> None:
            self.calls.append(argv)
            raise subprocess.CalledProcessError(1, argv)

        with self.assertRaises(subprocess.CalledProcessError):
            self.publish(run=api_failure)
        self.assertEqual(1, len(self.calls))

        self.calls.clear()

        def release_failure(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            result = self.run_gh(argv, **kwargs)
            if argv[1] == "release":
                raise subprocess.CalledProcessError(1, argv)
            return result

        with self.assertRaises(subprocess.CalledProcessError):
            self.publish(run=release_failure)
        self.assertEqual(2, len(self.calls))


if __name__ == "__main__":
    unittest.main()
