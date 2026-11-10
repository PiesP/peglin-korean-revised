"""Run the pinned OSV image and classify its SARIF result for GitHub Actions."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate SARIF key: {key}")
        result[key] = value
    return result


def reject_constant(value: str) -> None:
    raise ValueError(f"Invalid JSON constant: {value}")


def finding_count(path: Path) -> int:
    """Check the pinned scanner's report structure before allowing publication."""
    report = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=unique_object,
        parse_constant=reject_constant,
    )
    if not isinstance(report, dict) or report.get("version") != "2.1.0":
        raise ValueError("Expected SARIF version 2.1.0")
    runs = report.get("runs")
    if not isinstance(runs, list) or not runs:
        raise ValueError("Expected at least one SARIF run")
    count = 0
    for run in runs:
        if not isinstance(run, dict):
            raise ValueError("Invalid SARIF run")
        tool = run.get("tool")
        driver = tool.get("driver") if isinstance(tool, dict) else None
        if not isinstance(driver, dict) or driver.get("name") != "osv-scanner":
            raise ValueError("Expected osv-scanner driver")
        if "invocations" in run:
            invocations = run["invocations"]
            if (
                not isinstance(invocations, list)
                or not invocations
                or any(
                    not isinstance(item, dict) or item.get("executionSuccessful") is not True
                    for item in invocations
                )
            ):
                raise ValueError("SARIF invocation did not complete successfully")
        results = run.get("results")
        if not isinstance(results, list):
            raise ValueError("Expected explicit SARIF results")
        for result in results:
            if not isinstance(result, dict) or not isinstance(result.get("message"), dict):
                raise ValueError("Invalid SARIF result")
            if not isinstance(result["message"].get("text"), str):
                raise ValueError("Expected SARIF result message text")
        count += len(results)
    return count


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
    config_path = result_dir / "policy.toml"
    try:
        result_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        result_dir.chmod(0o700)
        result_path.unlink(missing_ok=True)
        # No findings are excepted. Candidate-local scanner configs cannot add ignores.
        config_path.write_text("IgnoredVulns = []\nPackageOverrides = []\n", encoding="utf-8")
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
        "--config=/results/policy.toml",
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
        findings = finding_count(result_path)
    except (OSError, ValueError) as exc:
        print(f"Invalid OSV SARIF report: {exc}", file=sys.stderr)
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
        print("::error::OSV findings block merging; review the uploaded report.")
        return 1
    if findings:
        print("::error::OSV report contains findings despite scanner exit 0.")
        return 1
    try:
        with github_output.open("a", encoding="utf-8") as output:
            output.write("policy=clean\n")
    except OSError as exc:
        print(f"Could not record OSV policy output: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
