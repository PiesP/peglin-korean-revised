from __future__ import annotations

import importlib.util
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github" / "scripts" / "resolve_toolchains.py"
VALIDATE = ROOT / ".github" / "workflows" / "validate.yml"
SPEC = importlib.util.spec_from_file_location("resolve_toolchains", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Could not load maintenance toolchain resolver.")
toolchains = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(toolchains)


class ToolchainSelectionTests(unittest.TestCase):
    def test_repository_selects_patched_uv_with_python_314(self) -> None:
        python, uv = toolchains.resolve_toolchains(ROOT / "pyproject.toml")
        self.assertEqual("3.14", python)
        self.assertGreaterEqual(tuple(map(int, uv.split("."))), (0, 13, 4))

    def test_validation_keeps_maintenance_and_patched_311_lanes(self) -> None:
        workflow = VALIDATE.read_text(encoding="utf-8")
        maintenance = workflow.split("  python-maintenance:\n", 1)[1].split(
            "\n  python-compat:\n", 1
        )[0]
        compatibility = workflow.split("\n  python-compat:\n", 1)[1].split("\n  validate:\n", 1)[0]
        self.assertIn("python-version: ${{ steps.toolchains.outputs.python }}", maintenance)
        self.assertIn("python-version: '3.11'", compatibility)
        for lane in (maintenance, compatibility):
            with self.subTest(lane=lane.splitlines()[0]):
                self.assertIn("check-latest: true", lane)
                self.assertIn(".github/scripts/verify_python.py", lane)
                self.assertIn(
                    'uv sync --locked --python "${{ steps.setup-python.outputs.python-path }}"',
                    lane,
                )
                self.assertIn("-m compileall -q src/peglin_l10n", lane)
                self.assertIn("-m unittest discover -s tests -v", lane)
                self.assertIn("peglin-l10n lint-overrides", lane)
        self.assertIn("verify_python.py 3.11 --selected-executable", compatibility)

    def test_required_validate_rejects_non_successful_python_lane(self) -> None:
        workflow = VALIDATE.read_text(encoding="utf-8")
        aggregate = workflow.split("\n  validate:\n", 1)[1]
        self.assertIn("    name: validate\n", aggregate)
        self.assertIn("    needs: [python-maintenance, python-compat]\n", aggregate)
        self.assertIn("    if: ${{ always() }}\n", aggregate)
        self.assertIn("MAINTENANCE_RESULT: ${{ needs.python-maintenance.result }}", aggregate)
        self.assertIn("COMPAT_RESULT: ${{ needs.python-compat.result }}", aggregate)
        script = textwrap.dedent(aggregate.split("        run: |\n", 1)[1])
        for maintenance, compatibility, succeeds in (
            ("success", "success", True),
            ("failure", "success", False),
            ("success", "skipped", False),
            ("cancelled", "success", False),
            (None, "success", False),
            ("success", None, False),
        ):
            with self.subTest(maintenance=maintenance, compatibility=compatibility):
                environment = os.environ.copy()
                if maintenance is not None:
                    environment["MAINTENANCE_RESULT"] = maintenance
                else:
                    environment.pop("MAINTENANCE_RESULT", None)
                if compatibility is not None:
                    environment["COMPAT_RESULT"] = compatibility
                else:
                    environment.pop("COMPAT_RESULT", None)
                result = subprocess.run(
                    ["bash", "-e", "-o", "pipefail", "-c", script],
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(succeeds, result.returncode == 0, result.stdout + result.stderr)

    def test_reads_changed_versions_from_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pyproject.toml"
            path.write_text(
                '[tool.maintenance]\npython = "3.12"\nuv = "1.2.3"\n',
                encoding="utf-8",
            )
            self.assertEqual(("3.12", "1.2.3"), toolchains.resolve_toolchains(path))

    def test_rejects_missing_and_non_numeric_versions(self) -> None:
        invalid_tables = (
            '[tool.maintenance]\npython = "3.12"\n',
            '[tool.maintenance]\npython = """3.12\nuv=evil"""\nuv = "1.2.3"\n',
            '[tool.maintenance]\npython = "3.12.0"\nuv = "1.2.3"\n',
            '[tool.maintenance]\npython = "3.12"\nuv = "1.2.3-beta"\n',
            '[tool.maintenance]\npython = 3.12\nuv = "1.2.3"\n',
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pyproject.toml"
            for contents in invalid_tables:
                with self.subTest(contents=contents):
                    path.write_text(contents, encoding="utf-8")
                    with self.assertRaises((ValueError, TypeError)):
                        toolchains.resolve_toolchains(path)

    def test_writes_validated_action_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pyproject.toml").write_text(
                '[tool.maintenance]\npython = "3.12"\nuv = "1.2.3"\n',
                encoding="utf-8",
            )
            output = root / "github-output"
            output.write_text("prior=value\n", encoding="utf-8")
            with (
                patch.dict(os.environ, {"GITHUB_OUTPUT": str(output)}),
                patch.object(toolchains, "PROJECT_ROOT", root),
            ):
                toolchains.main()
            self.assertEqual(
                "prior=value\npython=3.12\nuv=1.2.3\n",
                output.read_text(encoding="utf-8"),
            )

    def test_rejects_output_injection_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pyproject.toml").write_text(
                '[tool.maintenance]\npython = """3.12\nuv=evil"""\nuv = "1.2.3"\n',
                encoding="utf-8",
            )
            output = root / "github-output"
            output.write_text("prior=value\n", encoding="utf-8")
            with (
                patch.dict(os.environ, {"GITHUB_OUTPUT": str(output)}),
                patch.object(toolchains, "PROJECT_ROOT", root),
            ):
                with self.assertRaises(ValueError):
                    toolchains.main()
            self.assertEqual("prior=value\n", output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
