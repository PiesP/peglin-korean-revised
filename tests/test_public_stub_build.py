import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / ".github/scripts/build_public_stub_plugin.sh"
STUB_PROJECTS = ("UnityEngine.CoreModule", "UnityEngine", "Assembly-CSharp", "Newtonsoft.Json")


class PublicStubBuildFailureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.reference_dir = self.root / "references"
        self.calls = self.root / "dotnet-calls"
        fake_dotnet = self.root / "dotnet"
        fake_dotnet.write_text(
            "#!/bin/sh\n"
            'printf "%s\\n" "$1" >> "$CALL_LOG"\n'
            'if [ "$1" = "$FAIL_COMMAND" ]; then exit 23; fi\n'
        )
        fake_dotnet.chmod(0o700)

    def run_stage(self, stage: str, fail_command: str = "none") -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.update(
            {
                "PATH": f"{self.root}:{environment['PATH']}",
                "CALL_LOG": str(self.calls),
                "FAIL_COMMAND": fail_command,
            }
        )
        return subprocess.run(
            ["bash", str(SCRIPT), stage, str(self.reference_dir)],
            cwd=self.root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_missing_public_stub_lock_stops_before_restore(self) -> None:
        for project in STUB_PROJECTS[:-1]:
            lockfile = self.root / f".github/codeql-reference-stubs/{project}/packages.lock.json"
            lockfile.parent.mkdir(parents=True)
            lockfile.touch()

        result = self.run_stage("stubs")

        self.assertNotEqual(0, result.returncode)
        self.assertIn("Missing public reference lockfile", result.stderr)
        self.assertFalse(self.calls.exists())

    def test_failed_locked_stub_restore_stops_before_build(self) -> None:
        for project in STUB_PROJECTS:
            lockfile = self.root / f".github/codeql-reference-stubs/{project}/packages.lock.json"
            lockfile.parent.mkdir(parents=True)
            lockfile.touch()

        result = self.run_stage("stubs", fail_command="restore")

        self.assertEqual(23, result.returncode)
        self.assertEqual("restore\n", self.calls.read_text())

    def test_failed_plugin_build_is_not_reported_as_success(self) -> None:
        lockfile = self.root / "plugin/packages.lock.json"
        lockfile.parent.mkdir()
        lockfile.touch()
        self.reference_dir.mkdir()
        for assembly in STUB_PROJECTS:
            (self.reference_dir / f"{assembly}.dll").touch()

        result = self.run_stage("plugin", fail_command="build")

        self.assertEqual(23, result.returncode)
        self.assertEqual("restore\nbuild\n", self.calls.read_text())


if __name__ == "__main__":
    unittest.main()
