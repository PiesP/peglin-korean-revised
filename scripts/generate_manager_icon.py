"""Render the original PKR SVG to the Thunderstore 256x256 PNG asset."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/peglin_l10n/assets/icon.svg"
DESTINATION = ROOT / "src/peglin_l10n/assets/icon.png"


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        rendered = Path(temporary) / "icon.png"
        subprocess.run(
            [
                "rsvg-convert",
                "--width",
                "256",
                "--height",
                "256",
                "--output",
                str(rendered),
                str(SOURCE),
            ],
            check=True,
        )
        data = rendered.read_bytes()
        if (
            data[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
            or data[16:24] != (256).to_bytes(4, "big") * 2
        ):
            raise ValueError("Renderer did not produce a 256x256 PNG.")
        DESTINATION.write_bytes(data)


if __name__ == "__main__":
    main()
