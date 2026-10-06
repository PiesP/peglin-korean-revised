"""Exercise publication wiring without network access or release creation."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_release_artifact_verifier import ReleaseFixture, SOURCE_SHA


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/release-translation.yml"


def publication_step(name: str) -> str:
    publish = WORKFLOW.read_text().split("  publish:\n", 1)[1]
    start = publish.index(f"      - name: {name}\n")
    end = publish.find("      - name: ", start + 1)
    return publish[start:] if end < 0 else publish[start:end]


def command(name: str) -> list[str]:
    step = publication_step(name)
    match = re.search(r"^        run: (.+)$", step, re.MULTILINE)
    if match is None:
        raise AssertionError("Publication step must be a thin helper invocation")
    argv = shlex.split(match.group(1))
    if argv[0] != "python3" or len(argv) != 2:
        raise AssertionError("Publication step must call one Python helper")
    return [sys.executable, argv[1]]


class ReleaseWorkflowTests(unittest.TestCase):
    def test_publication_loads_only_immutable_trusted_helpers(self) -> None:
        publish = WORKFLOW.read_text().split("  publish:\n", 1)[1]
        checkout = publication_step("Load reviewed publication helpers")
        self.assertRegex(checkout, r"ref: [0-9a-f]{40}\n")
        self.assertIn("repository: PiesP/peglin-korean-revised", checkout)
        self.assertIn("path: .trusted-release", checkout)
        self.assertIn("persist-credentials: false", checkout)
        self.assertIn("sparse-checkout-cone-mode: false", checkout)
        paths = checkout.split("          sparse-checkout: |\n", 1)[1].splitlines()
        self.assertEqual([
            ".github/scripts/verify_release_artifacts.py",
            ".github/scripts/publish_release.py",
        ], [line.strip() for line in paths])
        self.assertNotIn("${{", checkout)
        self.assertNotIn("uv ", publish)
        self.assertNotIn("pip ", publish)
        self.assertNotIn("UnityPy", publish)
        self.assertNotIn("python3 - <<", publish)
        self.assertNotIn("gh release create", publish)
        self.assertIn("needs: [verify-release-source, build]", publish)
        self.assertIn("needs.verify-release-source.outputs.eligible == 'true' && needs.build.result == 'success'", publish)
        self.assertIn("contents: write", publish)
        self.assertLess(publish.index("Load reviewed publication helpers"), publish.index("Verify provenance and checksums"))
        self.assertLess(publish.index("Verify provenance and checksums"), publish.index("Create release for the verified commit"))
        download = publication_step("Download files built by this workflow")
        self.assertNotIn("run-id:", download)
        self.assertNotIn("repository:", download)
        self.assertIn("needs.verify-release-source.outputs.release_tag", download)

    def test_publisher_receives_verified_outputs_and_original_tag_identity(self) -> None:
        verify = publication_step("Verify provenance and checksums")
        create = publication_step("Create release for the verified commit")
        self.assertIn("id: verify", verify)
        self.assertNotIn("GH_TOKEN", verify)
        for key in ("source_sha", "release_tag"):
            self.assertIn(f"needs.verify-release-source.outputs.{key}", verify)
        for key in ("tag", "prerelease", "overlay"):
            self.assertIn(f"steps.verify.outputs.{key}", create)
        self.assertIn("needs.verify-release-source.outputs.tag_object_sha", create)
        self.assertNotIn("continue-on-error", verify + create)
        self.assertNotIn("always()", create)
        self.assertNotIn("        if:", create)

    def test_real_workflow_helpers_stop_on_bad_data_and_recheck_tags(self) -> None:
        for mode in ("valid-rc", "valid-stable", "invalid", "moved-tag", "api-failure", "publish-failure"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory(prefix="release workflow ") as directory:
                root = Path(directory)
                release = root / "artifacts"
                release.mkdir()
                fixture = ReleaseFixture(release, prerelease=mode != "valid-stable")
                trusted = root / ".trusted-release/.github/scripts"
                trusted.mkdir(parents=True)
                for name in ("verify_release_artifacts.py", "publish_release.py"):
                    shutil.copyfile(ROOT / ".github/scripts" / name, trusted / name)
                bin_path = root / "bin"
                bin_path.mkdir()
                gh = bin_path / "gh"
                gh.write_text(
                    f"#!{sys.executable}\n"
                    "import json, os, sys\n"
                    "with open(os.environ['CALLS'], 'a') as log: log.write(json.dumps(sys.argv[1:]) + '\\n')\n"
                    "if sys.argv[1] == 'api':\n"
                    "    if os.environ['MODE'] == 'api-failure': sys.exit(7)\n"
                    "    print('e' * 40 if os.environ['MODE'] == 'moved-tag' else 'd' * 40)\n"
                    "elif os.environ['MODE'] == 'publish-failure': sys.exit(8)\n"
                )
                gh.chmod(0o755)
                output = root / "github-output"
                calls = root / "calls.jsonl"
                env = {**os.environ, "PATH": str(bin_path) + os.pathsep + os.environ.get("PATH", ""),
                       "RELEASE_DIR": str(release), "SOURCE_SHA": SOURCE_SHA,
                       "RELEASE_TAG": fixture.tag, "TAG_OBJECT_SHA": "d" * 40,
                       "GITHUB_REPOSITORY": "PiesP/peglin-korean-revised",
                       "GITHUB_OUTPUT": str(output), "CALLS": str(calls), "MODE": mode,
                       "GH_TOKEN": "synthetic-unused-token"}
                if mode == "invalid":
                    (release / "LICENSE").write_bytes(b"corrupt")
                verify = subprocess.run(command("Verify provenance and checksums"), cwd=root, env=env,
                                        capture_output=True, text=True, check=False)
                if mode == "invalid":
                    self.assertNotEqual(0, verify.returncode)
                    self.assertFalse(output.exists())
                    self.assertFalse(calls.exists())
                    continue
                self.assertEqual(0, verify.returncode, verify.stderr)
                values = dict(line.split("=", 1) for line in output.read_text().splitlines())
                env.update(RELEASE_TAG=values["tag"], PRERELEASE=values["prerelease"], OVERLAY_NAME=values["overlay"])
                result = subprocess.run(command("Create release for the verified commit"), cwd=root, env=env,
                                        capture_output=True, text=True, check=False)
                actual = [json.loads(line) for line in calls.read_text().splitlines()]
                if mode in {"moved-tag", "api-failure"}:
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual(1, len(actual))
                else:
                    self.assertEqual(2, len(actual))
                    self.assertEqual(["release", "create", fixture.tag], actual[1][:3])
                    self.assertEqual(mode != "valid-stable", "--prerelease" in actual[1])
                    self.assertEqual(mode == "publish-failure", result.returncode != 0)


if __name__ == "__main__":
    unittest.main()
