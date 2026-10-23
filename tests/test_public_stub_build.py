import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / ".github/scripts/build_public_stub_plugin.py"
SDK_POLICY = Path(__file__).resolve().parents[1] / "global.json"
STUB_PROJECTS = ("UnityEngine.CoreModule", "UnityEngine", "Assembly-CSharp", "Newtonsoft.Json")


class PublicStubBuildTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.reference_dir = self.root / "references with spaces"
        self.calls = self.root / "dotnet-calls"
        self.build_started = self.root / "build-started"
        self.runner_temp = self.root / "runner temp"
        self.runner_temp.mkdir()
        (self.root / "global.json").write_bytes(SDK_POLICY.read_bytes())
        fake_dotnet = self.root / "dotnet"
        fake_dotnet.write_text(
            f"#!{sys.executable}\n"
            "import json, os, pathlib, sys\n"
            "args = sys.argv[1:]\n"
            "with open(os.environ['CALL_LOG'], 'a') as log: log.write(json.dumps(args) + '\\n')\n"
            "if args[0] == os.environ.get('FAIL_COMMAND'): sys.exit(23)\n"
            "if args[0] == '--version':\n"
            "    print(os.environ.get('FAKE_SDK') or json.loads(pathlib.Path('global.json').read_text())['sdk']['version'])\n"
            "    sys.exit(0)\n"
            "if args[0] == 'build' and 'codeql-reference-stubs' in args[1]:\n"
            "    project = pathlib.Path(args[1]).stem\n"
            "    output = pathlib.Path(args[1]).parent / 'bin/Release/net46'\n"
            "    output.mkdir(parents=True, exist_ok=True)\n"
            "    for name in ([project, 'UnityEngine.CoreModule'] if project == 'UnityEngine' else [project]):\n"
            "        (output / (name + '.dll')).write_text(name)\n"
            "if args[0] == 'build' and 'PeglinKoreanRevised' in args[1]:\n"
            "    targets = next(arg.split('=', 1)[1] for arg in args if arg.startswith('-p:CustomAfter'))\n"
            "    assert pathlib.Path(targets).stat().st_mode & 0o777 == 0o600\n"
            "    assert 'Reference Remove=\"netstandard\"' in pathlib.Path(targets).read_text()\n"
            "    if os.environ.get('BLOCK_BUILD') == '1':\n"
            "        pathlib.Path(os.environ['BUILD_STARTED']).write_text(json.dumps({'pid': os.getpid(), 'targets': targets}))\n"
            "        import time\n"
            "        time.sleep(60)\n"
        )
        fake_dotnet.chmod(0o700)

    def locks(self, projects: tuple[str, ...] = STUB_PROJECTS) -> None:
        for project in projects:
            lockfile = self.root / f".github/codeql-reference-stubs/{project}/packages.lock.json"
            lockfile.parent.mkdir(parents=True, exist_ok=True)
            lockfile.touch()

    def plugin_inputs(self) -> None:
        lockfile = self.root / "plugin/packages.lock.json"
        lockfile.parent.mkdir(parents=True, exist_ok=True)
        lockfile.touch()
        self.reference_dir.mkdir()
        for assembly in STUB_PROJECTS:
            (self.reference_dir / f"{assembly}.dll").touch()

    def run_stage(
        self,
        stage: str,
        fail_command: str = "none",
        *,
        only_fixture_path: bool = False,
        fake_sdk: str = "",
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.update(
            {
                "PATH": str(self.root)
                if only_fixture_path
                else f"{self.root}:{environment['PATH']}",
                "CALL_LOG": str(self.calls),
                "FAIL_COMMAND": fail_command,
                "FAKE_SDK": fake_sdk,
                "RUNNER_TEMP": str(self.runner_temp),
            }
        )
        return subprocess.run(
            [sys.executable, str(SCRIPT), stage, str(self.reference_dir)],
            cwd=self.root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def recorded_calls(self) -> list[list[str]]:
        return [json.loads(line) for line in self.calls.read_text().splitlines()]

    def test_missing_public_stub_lock_stops_before_restore(self) -> None:
        self.locks(STUB_PROJECTS[:-1])
        result = self.run_stage("stubs")
        self.assertEqual(1, result.returncode)
        self.assertIn("Missing public reference lockfile", result.stderr)
        self.assertFalse(self.calls.exists())

    def test_failed_locked_stub_restore_stops_before_build(self) -> None:
        self.locks()
        result = self.run_stage("stubs", fail_command="restore")
        self.assertEqual(23, result.returncode)
        self.assertEqual(["--version", "restore"], [call[0] for call in self.recorded_calls()])
        self.assertFalse(self.reference_dir.exists())

    def test_stubs_preserve_command_order_and_publish_private_reference_directory(self) -> None:
        self.locks()
        result = self.run_stage("stubs")
        self.assertEqual(0, result.returncode, result.stderr)
        calls = self.recorded_calls()
        self.assertEqual(
            ["--version"] + ["restore"] * 3 + ["build"] * 3, [call[0] for call in calls]
        )
        expected = json.loads(SDK_POLICY.read_text())["sdk"]["version"]
        self.assertIn(f"Selected .NET SDK: {expected}", result.stdout)
        self.assertEqual(
            ["UnityEngine", "Assembly-CSharp", "Newtonsoft.Json"] * 2,
            [Path(call[1]).stem for call in calls[1:]],
        )
        self.assertTrue(all("--locked-mode" in call for call in calls[1:4]))
        self.assertTrue(all("--no-restore" in call for call in calls[4:]))
        self.assertEqual(0o700, stat.S_IMODE(self.reference_dir.stat().st_mode))
        self.assertEqual(
            {f"{assembly}.dll" for assembly in STUB_PROJECTS},
            {path.name for path in self.reference_dir.iterdir()},
        )

    def test_failed_plugin_build_cleans_targets_and_preserves_status(self) -> None:
        self.plugin_inputs()
        result = self.run_stage("plugin", fail_command="build")
        self.assertEqual(23, result.returncode)
        calls = self.recorded_calls()
        self.assertEqual(["--version", "restore", "build"], [call[0] for call in calls])
        self.assertIn(f"-p:PeglinManagedDir={self.reference_dir}", calls[1])
        self.assertIn("--locked-mode", calls[1])
        self.assertIn("--no-restore", calls[2])
        self.assertIn("-p:ContinuousIntegrationBuild=true", calls[2])
        self.assertEqual([], list(self.runner_temp.iterdir()))

    def test_successful_plugin_build_also_cleans_targets(self) -> None:
        self.plugin_inputs()
        result = self.run_stage("plugin")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual([], list(self.runner_temp.iterdir()))

    def test_missing_plugin_input_and_invalid_stage_never_start_dotnet(self) -> None:
        result = self.run_stage("plugin")
        self.assertEqual(1, result.returncode)
        self.assertIn("Missing plugin lockfile", result.stderr)
        self.plugin_inputs()
        (self.reference_dir / "Newtonsoft.Json.dll").unlink()
        result = self.run_stage("plugin")
        self.assertEqual(1, result.returncode)
        self.assertIn("Missing public reference assembly: Newtonsoft.Json.dll", result.stderr)
        result = self.run_stage("unknown")
        self.assertEqual(2, result.returncode)
        self.assertIn("Unknown build stage", result.stderr)
        self.assertFalse(self.calls.exists())

    def test_unusable_target_directory_stops_after_restore(self) -> None:
        self.plugin_inputs()
        self.runner_temp.rmdir()
        self.runner_temp.write_text("not a directory")
        result = self.run_stage("plugin")
        self.assertEqual(1, result.returncode)
        self.assertIn("Could not create public-stub targets", result.stderr)
        self.assertEqual(["--version", "restore"], [call[0] for call in self.recorded_calls()])

    def test_wrong_sdk_stops_before_restore_in_each_stage(self) -> None:
        self.locks()
        self.plugin_inputs()
        for stage in ("stubs", "plugin"):
            with self.subTest(stage=stage):
                self.calls.unlink(missing_ok=True)
                result = self.run_stage(stage, fake_sdk="8.0.426")
                self.assertEqual(1, result.returncode)
                expected = json.loads(SDK_POLICY.read_text())["sdk"]["version"]
                self.assertIn(f"Expected .NET SDK {expected}", result.stderr)
                self.assertEqual([["--version"]], self.recorded_calls())

    def test_failed_sdk_query_preserves_return_code(self) -> None:
        self.locks()
        result = self.run_stage("stubs", fail_command="--version")
        self.assertEqual(23, result.returncode)
        self.assertEqual([["--version"]], self.recorded_calls())

    def test_dotnet_start_failure_is_reported(self) -> None:
        self.locks()
        (self.root / "dotnet").unlink()
        result = self.run_stage("stubs", only_fixture_path=True)
        self.assertEqual(1, result.returncode)
        self.assertIn("Could not start dotnet", result.stderr)
        self.assertFalse(self.reference_dir.exists())

    def test_empty_reference_directory_is_rejected_without_changing_workspace_mode(self) -> None:
        self.locks()
        before_mode = stat.S_IMODE(self.root.stat().st_mode)
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "stubs", ""],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(2, result.returncode)
        self.assertIn("Expected a reference assembly directory", result.stderr)
        self.assertEqual(before_mode, stat.S_IMODE(self.root.stat().st_mode))

    def test_termination_reaps_owned_dotnet_child_and_removes_targets(self) -> None:
        self.plugin_inputs()
        environment = os.environ.copy()
        environment.update(
            {
                "PATH": f"{self.root}:{environment['PATH']}",
                "CALL_LOG": str(self.calls),
                "FAIL_COMMAND": "none",
                "RUNNER_TEMP": str(self.runner_temp),
                "BLOCK_BUILD": "1",
                "BUILD_STARTED": str(self.build_started),
            }
        )
        helper = subprocess.Popen(
            [sys.executable, str(SCRIPT), "plugin", str(self.reference_dir)],
            cwd=self.root,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        child_pid: int | None = None
        try:
            deadline = time.monotonic() + 5
            while not self.build_started.exists() and time.monotonic() < deadline:
                if helper.poll() is not None:
                    self.fail(f"build helper exited before plugin build: {helper.communicate()}")
                time.sleep(0.02)
            self.assertTrue(self.build_started.exists(), "plugin build did not start")
            started = json.loads(self.build_started.read_text())
            child_pid = started["pid"]
            targets = Path(started["targets"])
            self.assertTrue(targets.exists())
            helper.send_signal(signal.SIGTERM)
            _stdout, stderr = helper.communicate(timeout=5)
            self.assertEqual(143, helper.returncode, stderr)
            self.assertIn("interrupted by signal 15", stderr)
            self.assertFalse(targets.exists())
            self.assertEqual([], list(self.runner_temp.iterdir()))
            with self.assertRaises(ProcessLookupError):
                os.kill(child_pid, 0)
        finally:
            if helper.poll() is None:
                helper.kill()
                helper.communicate(timeout=5)
            if child_pid is not None:
                try:
                    os.kill(child_pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass


if __name__ == "__main__":
    unittest.main()
