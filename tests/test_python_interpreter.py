"""Check the CI Python security floor independently of the host interpreter."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / ".github/scripts/verify_python.py"
SPEC = importlib.util.spec_from_file_location("verify_python", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Could not load Python verification helper.")
verify_python = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify_python)


class PythonInterpreterTests(unittest.TestCase):
    def test_accepts_patched_gil_cpython_on_selected_executable(self) -> None:
        verify_python.verify_interpreter(
            "3.11", "cpython", (3, 11, 18), False, sys.executable, sys.executable
        )
        verify_python.verify_interpreter(
            "3.11", "cpython", (3, 11, 19), False, sys.executable, None
        )

    def test_rejects_old_patch_other_minor_and_other_implementation(self) -> None:
        for expected_minor, implementation, version in (
            ("3.11", "cpython", (3, 11, 17)),
            ("3.11", "cpython", (3, 12, 0)),
            ("3.11", "pypy", (3, 11, 18)),
            ("3.14", "cpython", (3, 14, 10)),
        ):
            with self.subTest(
                expected_minor=expected_minor, implementation=implementation, version=version
            ):
                with self.assertRaises(ValueError):
                    verify_python.verify_interpreter(
                        expected_minor, implementation, version, False, sys.executable, None
                    )

    def test_rejects_disabled_gil_and_different_project_interpreter(self) -> None:
        with self.assertRaisesRegex(ValueError, "GIL-enabled"):
            verify_python.verify_interpreter(
                "3.11", "cpython", (3, 11, 18), True, sys.executable, None
            )
        with tempfile.TemporaryDirectory() as directory:
            other = Path(directory) / "python"
            other.touch()
            with self.assertRaisesRegex(ValueError, "differs"):
                verify_python.verify_interpreter(
                    "3.11", "cpython", (3, 11, 18), False, sys.executable, str(other)
                )


if __name__ == "__main__":
    unittest.main()
