"""Command line entry point for extraction, diff, and review checks."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Sequence

from .candidate import create_client_candidate
from .diffing import compare_snapshots
from .extract import (
    DEFAULT_GAME_ROOT,
    ExtractionError,
    InstallationData,
    default_output_dir,
    load_installation,
    snapshot_csv_bytes,
    write_snapshot,
)
from .fingerprints import source_fingerprint
from .patching import create_overlay_patch
from .validation import index_terms_csv, lint_overrides, validate

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="peglin-l10n")
    subparsers = parser.add_subparsers(dest="command", required=True)

    extract = subparsers.add_parser("extract", help="extract the installed I2 language table")
    extract.add_argument(
        "--game-root",
        type=Path,
        default=Path(os.environ.get("PEGLIN_GAME_ROOT", DEFAULT_GAME_ROOT)),
        help="Peglin installation directory",
    )
    extract.add_argument("--output-dir", type=Path, help="exact output snapshot directory")

    build_patch = subparsers.add_parser(
        "build-patch",
        help="extract the installed game and build a source-bound Korean JSON overlay",
    )
    build_patch.add_argument(
        "--game-root",
        type=Path,
        default=Path(os.environ.get("PEGLIN_GAME_ROOT", DEFAULT_GAME_ROOT)),
        help="Peglin installation directory",
    )
    build_patch.add_argument(
        "--extracted-dir",
        type=Path,
        default=PROJECT_ROOT / "extracted",
        help="root directory for immutable source snapshots",
    )
    build_patch.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "patches" / "generated",
        help="directory for generated overlay JSON files",
    )
    build_patch.add_argument(
        "--glossary",
        type=Path,
        default=PROJECT_ROOT / "translation" / "glossary.csv",
    )
    build_patch.add_argument(
        "--overrides",
        type=Path,
        default=PROJECT_ROOT / "translation" / "overrides.json",
    )

    build_candidate = subparsers.add_parser(
        "build-candidate",
        help="build a source-bound BepInEx plugin candidate for the installed Peglin game",
    )
    build_candidate.add_argument(
        "--game-root",
        type=Path,
        default=Path(os.environ.get("PEGLIN_GAME_ROOT", DEFAULT_GAME_ROOT)),
        help="Peglin installation directory",
    )
    build_candidate.add_argument(
        "--extracted-dir",
        type=Path,
        default=PROJECT_ROOT / "extracted",
        help="root directory for immutable source snapshots",
    )
    build_candidate.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "patches" / "generated",
        help="directory for the generated JSON overlay",
    )
    build_candidate.add_argument(
        "--candidate-dir",
        type=Path,
        default=PROJECT_ROOT / "patches" / "candidates",
        help="directory for the installable ZIP candidate",
    )
    build_candidate.add_argument(
        "--plugin-project",
        type=Path,
        default=PROJECT_ROOT / "plugin" / "PeglinKoreanRevised.csproj",
        help="BepInEx plugin project to compile",
    )
    build_candidate.add_argument(
        "--dotnet",
        default="dotnet",
        help="path or command name for the .NET SDK",
    )
    build_candidate.add_argument(
        "--glossary",
        type=Path,
        default=PROJECT_ROOT / "translation" / "glossary.csv",
    )
    build_candidate.add_argument(
        "--overrides",
        type=Path,
        default=PROJECT_ROOT / "translation" / "overrides.json",
    )

    lint = subparsers.add_parser(
        "lint-overrides",
        help="validate override structure without requiring the installed game",
    )
    lint.add_argument(
        "--overrides",
        type=Path,
        default=PROJECT_ROOT / "translation" / "overrides.json",
    )

    validator = subparsers.add_parser("validate", help="validate a source CSV and overrides")
    validator.add_argument("--terms", required=True, type=Path, help="terms.csv snapshot")
    validator.add_argument(
        "--glossary",
        type=Path,
        default=PROJECT_ROOT / "translation" / "glossary.csv",
    )
    validator.add_argument(
        "--overrides",
        type=Path,
        default=PROJECT_ROOT / "translation" / "overrides.json",
    )
    validator.add_argument(
        "--source-manifest",
        type=Path,
        help="source.json paired with --terms (defaults to the same directory)",
    )

    diff = subparsers.add_parser("diff", help="compare two source snapshots")
    diff.add_argument("--old", required=True, type=Path, help="older terms.csv")
    diff.add_argument("--new", required=True, type=Path, help="newer terms.csv")
    diff.add_argument(
        "--overrides",
        type=Path,
        default=PROJECT_ROOT / "translation" / "overrides.json",
    )
    diff.add_argument("--output", type=Path, help="write JSON report to this path")

    fingerprint = subparsers.add_parser(
        "fingerprint", help="get the current source fingerprint for one term"
    )
    fingerprint.add_argument("--terms", required=True, type=Path, help="terms.csv snapshot")
    fingerprint.add_argument("--term", required=True, help="exact I2 term key")
    return parser


def _run_extract(args: argparse.Namespace) -> int:
    data = load_installation(args.game_root)
    output_dir = args.output_dir or default_output_dir(data)
    snapshot = write_snapshot(data, output_dir)
    manifest = json.loads((snapshot / "source.json").read_text(encoding="utf-8"))
    print(f"Extracted {manifest['termCount']} terms from Steam build {manifest['steamBuildId'] or 'unknown'}.")
    print(f"Official Korean is empty for {manifest['missingKoreanWithEnglish']} terms with English source.")
    print(
        "Dev Notes: "
        f"{manifest['devNotesNonblankCount']} nonblank values "
        f"({manifest['devNotesNonemptyCount']} nonempty fields)."
    )
    print(f"Snapshot: {snapshot}")
    return 0


def _snapshot_for_build(data: InstallationData, extracted_dir: Path) -> Path:
    """Reuse a matching immutable snapshot or write a new build/hash directory."""
    base_name = default_output_dir(data).name
    extracted_dir = extracted_dir.expanduser().resolve()
    candidates = (
        extracted_dir / base_name,
        extracted_dir / f"{base_name}-{data.asset_sha256[:8]}",
    )
    for candidate in candidates:
        if not candidate.exists():
            return write_snapshot(data, candidate)
        manifest_path = candidate / "source.json"
        terms_path = candidate / "terms.csv"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ExtractionError(
                f"Existing snapshot cannot be verified; preserving it: {candidate}"
            ) from exc
        if not isinstance(manifest, dict):
            raise ExtractionError(
                f"Existing snapshot manifest is not an object; preserving it: {candidate}"
            )
        matches_installation = (
            manifest.get("assetPath") == str(data.asset_path)
            and manifest.get("assetSha256") == data.asset_sha256
            and manifest.get("steamBuildId") == data.build_id
            and manifest.get("unityVersion") == data.unity_version
            and manifest.get("termCount") == len(data.table.terms)
        )
        if matches_installation:
            if not terms_path.is_file() or terms_path.read_bytes() != snapshot_csv_bytes(data):
                raise ExtractionError(
                    f"Existing snapshot does not match the installed source; preserving it: {candidate}"
                )
            return candidate
    raise ExtractionError(
        "Snapshot path is occupied by different source data; choose a separate "
        f"--extracted-dir: {candidates[-1]}"
    )


def _create_current_overlay(
    args: argparse.Namespace,
) -> tuple[InstallationData, Path, Path, dict[str, object]]:
    data = load_installation(args.game_root)
    if not isinstance(data.build_id, str) or not data.build_id.strip():
        raise ExtractionError("A Steam build ID is required to produce a source-bound overlay.")
    snapshot = _snapshot_for_build(data, args.extracted_dir)
    manifest = json.loads((snapshot / "source.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("Source manifest root must be a JSON object.")
    build_id = manifest.get("steamBuildId")
    if (
        not isinstance(build_id, str)
        or re.fullmatch(r"[A-Za-z0-9._-]{1,64}", build_id) is None
    ):
        raise ValueError("Source manifest steamBuildId cannot be used in a patch filename.")
    asset_sha256 = manifest.get("assetSha256")
    if (
        not isinstance(asset_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", asset_sha256) is None
    ):
        raise ValueError("Source manifest assetSha256 must be a lowercase SHA-256 digest.")
    output_path = args.output_dir.expanduser().resolve() / (
        f"peglin-ko-{build_id}-{asset_sha256[:8]}.json"
    )
    result = create_overlay_patch(
        snapshot / "terms.csv",
        snapshot / "source.json",
        args.overrides,
        args.glossary,
        output_path,
    )
    return data, snapshot, output_path, result


def _run_build_patch(args: argparse.Namespace) -> int:
    try:
        _, snapshot, output_path, result = _create_current_overlay(args)
    except (ExtractionError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Patch generation stopped safely: {exc}", file=sys.stderr)
        return 2
    print(f"Snapshot: {snapshot}")
    print(f"Patch status: {result['status']}")
    print(f"Translated terms: {len(result['terms'])}")
    print(f"Patch: {output_path}")
    return 0


def _run_build_candidate(args: argparse.Namespace) -> int:
    try:
        game_root = args.game_root.expanduser().resolve()
        output_paths = (
            ("extracted snapshots", args.extracted_dir),
            ("JSON overlay", args.output_dir),
            ("candidate ZIP", args.candidate_dir),
            ("plugin build", args.plugin_project.parent),
        )
        for output_name, output_path in output_paths:
            resolved_path = output_path.expanduser().resolve()
            if resolved_path == game_root or resolved_path.is_relative_to(game_root):
                raise ValueError(
                    f"The {output_name} path must be outside the Peglin installation directory."
                )

        data, snapshot, overlay_path, result = _create_current_overlay(args)
        candidate_path = create_client_candidate(
            overlay_path,
            data.game_root,
            args.candidate_dir,
            args.plugin_project,
            args.dotnet,
        )
    except (ExtractionError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Client candidate generation stopped safely: {exc}", file=sys.stderr)
        return 2
    print(f"Snapshot: {snapshot}")
    print(f"Patch status: {result['status']}")
    print(f"Translated terms: {len(result['terms'])}")
    print(f"Overlay: {overlay_path}")
    print(f"Candidate: {candidate_path}")
    return 0


def _run_lint_overrides(args: argparse.Namespace) -> int:
    try:
        summary, issues = lint_overrides(args.overrides)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Override lint could not run: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    for issue in issues:
        location = f" [{issue.term}]" if issue.term else ""
        print(f"{issue.severity.upper()} {issue.code}{location}: {issue.message}")
    return 1 if summary["errors"] else 0


def _run_validate(args: argparse.Namespace) -> int:
    try:
        summary, issues = validate(
            args.terms,
            args.glossary,
            args.overrides,
            args.source_manifest,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Validation could not run: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    for issue in issues:
        location = f" [{issue.term}]" if issue.term else ""
        print(f"{issue.severity.upper()} {issue.code}{location}: {issue.message}")
    return 1 if summary["errors"] else 0


def _run_diff(args: argparse.Namespace) -> int:
    try:
        report = compare_snapshots(args.old, args.new, args.overrides)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Diff could not run: {exc}", file=sys.stderr)
        return 2
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
        print(f"Wrote diff report: {args.output}")
    else:
        print(serialized, end="")
    return 0


def _run_fingerprint(args: argparse.Namespace) -> int:
    try:
        rows = index_terms_csv(args.terms)
    except (OSError, ValueError) as exc:
        print(f"Fingerprint could not be read: {exc}", file=sys.stderr)
        return 2
    row = rows.get(args.term)
    if row is None:
        print(f"Term not found: {args.term}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {"term": args.term, "sourceFingerprint": source_fingerprint(row)},
            ensure_ascii=False,
        )
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "extract":
            return _run_extract(args)
        if args.command == "build-patch":
            return _run_build_patch(args)
        if args.command == "build-candidate":
            return _run_build_candidate(args)
        if args.command == "lint-overrides":
            return _run_lint_overrides(args)
        if args.command == "validate":
            return _run_validate(args)
        if args.command == "diff":
            return _run_diff(args)
        if args.command == "fingerprint":
            return _run_fingerprint(args)
    except ExtractionError as exc:
        print(f"Extraction stopped safely: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
