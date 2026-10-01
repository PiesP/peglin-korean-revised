from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github" / "scripts" / "resolve_toolchains.py"
SPEC = importlib.util.spec_from_file_location("resolve_toolchains", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Could not load maintenance toolchain resolver.")
toolchains = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(toolchains)


class ToolchainSelectionTests(unittest.TestCase):
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
            with patch.dict(os.environ, {"GITHUB_OUTPUT": str(output)}), patch.object(
                toolchains, "PROJECT_ROOT", root
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
            with patch.dict(os.environ, {"GITHUB_OUTPUT": str(output)}), patch.object(
                toolchains, "PROJECT_ROOT", root
            ):
                with self.assertRaises(ValueError):
                    toolchains.main()
            self.assertEqual("prior=value\n", output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
