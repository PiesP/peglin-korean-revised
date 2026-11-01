"""Verify and describe the maintained CI interpreter before running project code."""

from __future__ import annotations

import argparse
import os
import platform
import sys
import sysconfig


def verify_interpreter(
    expected_minor: str,
    implementation: str,
    version: tuple[int, int, int],
    gil_disabled: bool,
    base_executable: str,
    selected_executable: str | None,
) -> None:
    if expected_minor != "3.11":
        raise ValueError("The maintained Python selector must be 3.11.")
    if implementation != "cpython" or not (3, 11, 18) <= version < (3, 12, 0):
        raise ValueError("CI requires CPython 3.11.18 or a later 3.11 security patch.")
    if gil_disabled:
        raise ValueError("CI requires ordinary GIL-enabled CPython.")
    if selected_executable is not None and not os.path.samefile(
        base_executable, selected_executable
    ):
        raise ValueError("The uv project interpreter differs from setup-python's interpreter.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("expected_minor")
    parser.add_argument("--selected-executable")
    args = parser.parse_args()

    base_executable = getattr(sys, "_base_executable", sys.executable)
    print(f"Python implementation: {sys.implementation.name}")
    print(f"Python version: {sys.version}")
    print(f"Python executable: {sys.executable}")
    print(f"Python base executable: {base_executable}")
    print(f"Python platform: {platform.platform()}")
    print(f"Python GIL disabled: {bool(sysconfig.get_config_var('Py_GIL_DISABLED'))}")
    verify_interpreter(
        args.expected_minor,
        sys.implementation.name,
        sys.version_info[:3],
        bool(sysconfig.get_config_var("Py_GIL_DISABLED")),
        base_executable,
        args.selected_executable,
    )


if __name__ == "__main__":
    main()
