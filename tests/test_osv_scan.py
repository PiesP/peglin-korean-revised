import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github/scripts/run_osv_scan.py"
SECURITY_WORKFLOW = ROOT / ".github/workflows/security.yaml"
CSHARP_WORKFLOW = ROOT / ".github/workflows/csharp-build.yml"


class OsvScanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.runner_temp = self.root / "runner temp"
        self.runner_temp.mkdir()
        self.workspace = self.root / "source with spaces"
        self.workspace.mkdir()
        self.output = self.root / "github-output"
        self.calls = self.root / "docker-calls"
        docker = self.root / "docker"
        docker.write_text(
            f"#!{sys.executable}\n"
            "import json, os, pathlib, sys\n"
            "args = sys.argv[1:]\n"
            "pathlib.Path(os.environ['CALL_LOG']).write_text(json.dumps(args))\n"
            "if os.environ['REPORT_KIND'] != 'missing':\n"
            "    result_dir = pathlib.Path(args[args.index('--volume') + 3].split(':/results')[0])\n"
            "    report = result_dir / 'osv-results.sarif'\n"
            "    report.write_text('SARIF' if os.environ['REPORT_KIND'] == 'valid' else '')\n"
            "if int(os.environ['SCAN_STATUS']) < 0:\n"
            "    import signal\n"
            "    os.kill(os.getpid(), -int(os.environ['SCAN_STATUS']))\n"
            "sys.exit(int(os.environ['SCAN_STATUS']))\n"
        )
        docker.chmod(0o700)

    def run_scan(
        self, status: int = 0, report_kind: str = "valid", *, only_fixture_path: bool = False
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.update(
            {
                "PATH": str(self.root)
                if only_fixture_path
                else f"{self.root}:{environment['PATH']}",
                "RUNNER_TEMP": str(self.runner_temp),
                "GITHUB_WORKSPACE": str(self.workspace),
                "GITHUB_OUTPUT": str(self.output),
                "OSV_SCANNER_IMAGE": "example.invalid/osv@sha256:abc",
                "CALL_LOG": str(self.calls),
                "SCAN_STATUS": str(status),
                "REPORT_KIND": report_kind,
            }
        )
        return subprocess.run(
            [sys.executable, str(SCRIPT)],
            cwd=self.root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def report(self) -> Path:
        return self.runner_temp / "osv-results/osv-results.sarif"

    def test_clean_scan_preserves_docker_contract_and_output(self) -> None:
        result = self.run_scan()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("report=true\n", self.output.read_text())
        self.assertEqual(0o700, stat.S_IMODE(self.report().parent.stat().st_mode))
        self.assertEqual(
            [
                "run",
                "--rm",
                "--volume",
                f"{self.workspace}:/src:ro",
                "--volume",
                f"{self.report().parent}:/results",
                "--workdir",
                "/src",
                "example.invalid/osv@sha256:abc",
                "--format=sarif",
                "--output-file=/results/osv-results.sarif",
                "--lockfile=uv.lock",
                "--lockfile=plugin/packages.lock.json",
                ".",
            ],
            json.loads(self.calls.read_text()),
        )

    def test_findings_emit_warning_and_allow_upload(self) -> None:
        result = self.run_scan(status=1)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("::warning::Known vulnerable dependencies", result.stdout)
        self.assertEqual("report=true\n", self.output.read_text())

    def test_operational_error_preserves_status_and_allows_report_upload(self) -> None:
        result = self.run_scan(status=23)
        self.assertEqual(23, result.returncode)
        self.assertIn("failed before completing the scan (exit 23)", result.stderr)
        self.assertEqual("report=true\n", self.output.read_text())

    def test_signaled_scanner_is_an_operational_failure(self) -> None:
        result = self.run_scan(status=-15)
        self.assertEqual(143, result.returncode)
        self.assertIn("failed before completing the scan (exit 143)", result.stderr)
        self.assertEqual("report=true\n", self.output.read_text())

    def test_missing_and_empty_reports_fail_without_output(self) -> None:
        for kind in ("missing", "empty"):
            with self.subTest(kind=kind):
                result = self.run_scan(report_kind=kind)
                self.assertEqual(1, result.returncode)
                self.assertIn("did not produce a SARIF report", result.stderr)
                self.assertFalse(self.output.exists())

    def test_stale_report_is_removed_before_scan(self) -> None:
        self.report().parent.mkdir()
        self.report().write_text("stale")
        result = self.run_scan(report_kind="missing")
        self.assertEqual(1, result.returncode)
        self.assertFalse(self.report().exists())
        self.assertFalse(self.output.exists())

    def test_command_start_failure_does_not_allow_upload(self) -> None:
        (self.root / "docker").unlink()
        result = self.run_scan(only_fixture_path=True)
        self.assertEqual(1, result.returncode)
        self.assertIn("Could not start OSV-Scanner", result.stderr)
        self.assertFalse(self.output.exists())

    def test_output_write_and_cleanup_failures_are_detected(self) -> None:
        self.output.mkdir()
        result = self.run_scan()
        self.assertEqual(1, result.returncode)
        self.assertIn("Could not record OSV SARIF report output", result.stderr)
        self.output.rmdir()
        self.report().unlink()
        self.report().mkdir()
        result = self.run_scan()
        self.assertEqual(1, result.returncode)
        self.assertIn("Could not prepare OSV result directory", result.stderr)
        self.assertFalse(self.output.exists())

    def test_workflows_keep_public_build_order_and_sarif_guard(self) -> None:
        security = SECURITY_WORKFLOW.read_text()
        csharp = CSHARP_WORKFLOW.read_text()
        self.assertLess(
            security.index("build_public_stub_plugin.py stubs"),
            security.index("- name: Initialize CodeQL"),
        )
        self.assertLess(
            security.index("- name: Initialize CodeQL"),
            security.index("build_public_stub_plugin.py plugin"),
        )
        self.assertIn("run: python3 .github/scripts/run_osv_scan.py", security)
        self.assertIn("steps.scan.outputs.report == 'true'", security)
        self.assertIn("sarif_file: ${{ runner.temp }}/osv-results/osv-results.sarif", security)
        self.assertIn("build_public_stub_plugin.py stubs", csharp)
        self.assertIn("build_public_stub_plugin.py plugin", csharp)


if __name__ == "__main__":
    unittest.main()
