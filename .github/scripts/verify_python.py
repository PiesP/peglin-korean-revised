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
    jit_enabled: bool,
    base_executable: str,
    selected_executable: str | None,
) -> None:
    floors = {"3.11": (3, 11, 18), "3.14": (3, 14, 10)}
    floor = floors.get(expected_minor)
    if floor is None:
        raise ValueError(f"Unsupported CI Python selector: {expected_minor}.")
    if implementation != "cpython" or version[:2] != floor[:2] or version < floor:
        raise ValueError(
            f"CI requires CPython {floor[0]}.{floor[1]}.{floor[2]} or a later {expected_minor} patch."
        )
    if gil_disabled:
        raise ValueError("CI requires ordinary GIL-enabled CPython.")
    if jit_enabled:
        raise ValueError("CI requires CPython with the experimental JIT disabled.")
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
    jit_enabled = bool(getattr(getattr(sys, "_jit", None), "is_enabled", lambda: False)())
    print(f"Python implementation: {sys.implementation.name}")
    print(f"Python version: {sys.version}")
    print(f"Python build: {platform.python_build()}")
    print(f"Python executable: {sys.executable}")
    print(f"Python base executable: {base_executable}")
    print(f"Python platform: {platform.platform()}")
    print(f"Python GIL disabled: {bool(sysconfig.get_config_var('Py_GIL_DISABLED'))}")
    print(f"Python JIT enabled: {jit_enabled}")
    verify_interpreter(
        args.expected_minor,
        sys.implementation.name,
        sys.version_info[:3],
        bool(sysconfig.get_config_var("Py_GIL_DISABLED")),
        jit_enabled,
        base_executable,
        args.selected_executable,
    )


if __name__ == "__main__":
    main()
