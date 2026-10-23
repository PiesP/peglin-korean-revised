"""The optional game reader must fail before writing any outputs."""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from peglin_l10n.cli import main


class OptionalExtractTests(unittest.TestCase):
    def test_missing_unitypy_preserves_outputs_for_game_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game_root = root / "game"
            asset = game_root / "Peglin_Data" / "resources.assets"
            asset.parent.mkdir(parents=True)
            asset.write_bytes(b"fixture asset")

            outputs = [root / name for name in ("snapshot", "overlay", "candidate")]
            for output in outputs:
                output.mkdir()
                (output / "previous.txt").write_text("preserve", encoding="utf-8")

            commands = (
                ["extract", "--output-dir", str(outputs[0])],
                [
                    "build-patch",
                    "--extracted-dir",
                    str(outputs[0]),
                    "--output-dir",
                    str(outputs[1]),
                ],
                [
                    "build-candidate",
                    "--extracted-dir",
                    str(outputs[0]),
                    "--output-dir",
                    str(outputs[1]),
                    "--candidate-dir",
                    str(outputs[2]),
                ],
            )
            for command in commands:
                with self.subTest(command=command[0]):
                    stderr = io.StringIO()
                    with patch.dict(sys.modules, {"UnityPy": None}):
                        with contextlib.redirect_stderr(stderr):
                            result = main([*command, "--game-root", str(game_root)])
                    self.assertEqual(2, result)
                    self.assertIn(
                        "uv sync --locked --python 3.11 --extra extract", stderr.getvalue()
                    )
                    self.assertIn(
                        "uv run --locked --extra extract peglin-l10n ...", stderr.getvalue()
                    )
                    for output in outputs:
                        self.assertEqual(["previous.txt"], [p.name for p in output.iterdir()])
                        self.assertEqual(
                            "preserve", (output / "previous.txt").read_text(encoding="utf-8")
                        )
