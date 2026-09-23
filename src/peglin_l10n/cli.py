"""Command line entry point for extraction, diff, and review checks."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Sequence

from .diffing import compare_snapshots
from .extract import DEFAULT_GAME_ROOT, ExtractionError, default_output_dir, load_installation, write_snapshot
from .fingerprints import source_fingerprint
from .validation import index_terms_csv, validate

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
