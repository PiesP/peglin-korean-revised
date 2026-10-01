"""Read the CI toolchain selections from pyproject.toml."""

from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def resolve_toolchains(path: Path) -> tuple[str, str]:
    with path.open("rb") as stream:
        config = tomllib.load(stream)
    maintenance = config.get("tool", {}).get("maintenance", {})
    python = maintenance.get("python")
    uv = maintenance.get("uv")
    if not isinstance(python, str) or not re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", python):
        raise ValueError("tool.maintenance.python must be a numeric major.minor version")
    if not isinstance(uv, str) or not re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", uv):
        raise ValueError("tool.maintenance.uv must be a numeric major.minor.patch version")
    return python, uv


def main() -> None:
    python, uv = resolve_toolchains(PROJECT_ROOT / "pyproject.toml")
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as stream:
        stream.write(f"python={python}\nuv={uv}\n")


if __name__ == "__main__":
    main()
