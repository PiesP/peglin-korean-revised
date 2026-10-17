"""Run the pinned OSV image and classify its SARIF result for GitHub Actions."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    try:
        runner_temp = Path(os.environ["RUNNER_TEMP"])
        workspace = os.environ["GITHUB_WORKSPACE"]
        image = os.environ["OSV_SCANNER_IMAGE"]
        github_output = Path(os.environ["GITHUB_OUTPUT"])
    except KeyError as exc:
        print(f"Missing OSV scan environment: {exc.args[0]}", file=sys.stderr)
        return 1

    result_dir = runner_temp / "osv-results"
    result_path = result_dir / "osv-results.sarif"
    try:
        result_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        result_dir.chmod(0o700)
        result_path.unlink(missing_ok=True)
    except OSError as exc:
        print(f"Could not prepare OSV result directory: {exc}", file=sys.stderr)
        return 1

    command = [
        "docker",
        "run",
        "--rm",
        "--volume",
        f"{workspace}:/src:ro",
        "--volume",
        f"{result_dir}:/results",
        "--workdir",
        "/src",
        image,
        "--format=sarif",
        "--output-file=/results/osv-results.sarif",
        "--lockfile=uv.lock",
        "--lockfile=plugin/packages.lock.json",
        ".",
    ]
    try:
        returncode = subprocess.run(command, check=False).returncode
        scan_status = returncode if returncode >= 0 else 128 - returncode
    except OSError as exc:
        print(f"Could not start OSV-Scanner: {exc}", file=sys.stderr)
        scan_status = 1

    try:
        has_report = result_path.is_file() and result_path.stat().st_size > 0
    except OSError as exc:
        print(f"Could not inspect OSV SARIF report: {exc}", file=sys.stderr)
        return scan_status if scan_status > 0 else 1
    if not has_report:
        print("OSV-Scanner did not produce a SARIF report.", file=sys.stderr)
        return scan_status if scan_status > 0 else 1

    try:
        with github_output.open("a", encoding="utf-8") as output:
            output.write("report=true\n")
    except OSError as exc:
        print(f"Could not record OSV SARIF report output: {exc}", file=sys.stderr)
        return scan_status if scan_status > 0 else 1

    if scan_status > 1:
        print(
            f"OSV-Scanner failed before completing the scan (exit {scan_status}).",
            file=sys.stderr,
        )
        return scan_status
    if scan_status == 1:
        print("::warning::Known vulnerable dependencies were found; review the Security tab.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
