"""CLI stream behavior when Windows redirects stdout through a legacy code page."""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from peglin_l10n.cli import main
from peglin_l10n.validation import Issue


class CliOutputTests(unittest.TestCase):
    def test_lint_and_validate_keep_json_on_legacy_stdout(self) -> None:
        commands = (
            ("lint-overrides", ["lint-overrides"], "lint_overrides"),
            ("validate", ["validate", "--terms", "unused.csv"], "validate"),
        )
        for name, argv, function in commands:
            for severity, expected_exit in (("warning", 0), ("error", 1)):
                with self.subTest(command=name, severity=severity):
                    summary = {
                        "errors": int(severity == "error"),
                        "warnings": int(severity == "warning"),
                    }
                    issue = Issue(severity, "KOREAN_TEXT", "한글 진단", "항목")
                    stdout_bytes = io.BytesIO()
                    stderr_bytes = io.BytesIO()
                    stdout = io.TextIOWrapper(stdout_bytes, encoding="cp1252", errors="strict")
                    stderr = io.TextIOWrapper(
                        stderr_bytes, encoding="cp1252", errors="backslashreplace"
                    )
                    with (
                        patch(f"peglin_l10n.cli.{function}", return_value=(summary, [issue])),
                        redirect_stdout(stdout),
                        redirect_stderr(stderr),
                    ):
                        exit_code = main(argv)
                    stdout.flush()
                    stderr.flush()

                    self.assertEqual(expected_exit, exit_code)
                    self.assertEqual(summary, json.loads(stdout_bytes.getvalue()))
                    self.assertIn(b"KOREAN_TEXT", stderr_bytes.getvalue())
                    self.assertIn(b"\\u", stderr_bytes.getvalue())
                    self.assertNotIn(b"KOREAN_TEXT", stdout_bytes.getvalue())

    def test_utf8_stderr_keeps_readable_diagnostic(self) -> None:
        for argv, function in (
            (["lint-overrides"], "lint_overrides"),
            (["validate", "--terms", "unused.csv"], "validate"),
        ):
            with self.subTest(command=argv[0]):
                stdout_bytes = io.BytesIO()
                stderr_bytes = io.BytesIO()
                stdout = io.TextIOWrapper(stdout_bytes, encoding="utf-8")
                stderr = io.TextIOWrapper(stderr_bytes, encoding="utf-8")
                with (
                    patch(
                        f"peglin_l10n.cli.{function}",
                        return_value=(
                            {"errors": 0, "warnings": 1},
                            [Issue("warning", "KOREAN_TEXT", "한글 진단", "항목")],
                        ),
                    ),
                    redirect_stdout(stdout),
                    redirect_stderr(stderr),
                ):
                    exit_code = main(argv)
                stdout.flush()
                stderr.flush()
                self.assertEqual(0, exit_code)
                self.assertEqual({"errors": 0, "warnings": 1}, json.loads(stdout_bytes.getvalue()))
                self.assertIn(
                    "WARNING KOREAN_TEXT [항목]: 한글 진단",
                    stderr_bytes.getvalue().decode("utf-8"),
                )


if __name__ == "__main__":
    unittest.main()
