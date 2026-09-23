"""Build deterministic, reviewable Korean overlay patch artifacts."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .extract import APP_ID
from .fingerprints import source_fingerprint as compute_source_fingerprint
from .validation import lint_overrides, read_overrides, read_terms_csv, validate


_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


def _read_source_manifest(path: Path, term_count: int) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Source manifest root must be a JSON object.")
    if type(data.get("schemaVersion")) is not int or data.get("schemaVersion") != 1:
        raise ValueError("Source manifest schemaVersion must be 1.")
    if data.get("game") != "Peglin":
        raise ValueError("Source manifest game must be Peglin.")
    if data.get("steamAppId") != APP_ID:
        raise ValueError(f"Source manifest steamAppId must be {APP_ID}.")
    if type(data.get("termCount")) is not int or data.get("termCount") != term_count:
        raise ValueError(
            "Source manifest termCount does not match the terms CSV: "
            f"{data.get('termCount')!r} != {term_count}."
        )

    for field in ("steamBuildId", "unityVersion"):
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Source manifest {field} must be a nonempty string.")

    asset_sha256 = data.get("assetSha256")
    if (
        not isinstance(asset_sha256, str)
        or _SHA256_PATTERN.fullmatch(asset_sha256) is None
    ):
        raise ValueError("Source manifest assetSha256 must be a lowercase SHA-256 digest.")
    return data


def _reject_unsafe_output(
    output_path: Path,
    input_paths: tuple[Path, ...],
    manifest: dict[str, Any],
) -> None:
    resolved_output = output_path.resolve()
    if any(resolved_output == path.resolve() for path in input_paths):
        raise ValueError("Overlay output must not replace an input file.")

    asset_path_value = manifest.get("assetPath")
    if not isinstance(asset_path_value, str) or not asset_path_value.strip():
        raise ValueError("Source manifest assetPath must be a nonempty string.")
    asset_path = Path(asset_path_value)
    if not asset_path.is_absolute():
        raise ValueError("Source manifest assetPath must be absolute.")

    resolved_asset = asset_path.resolve()
    game_root = resolved_asset.parent.parent
    if resolved_output == resolved_asset or resolved_output.is_relative_to(game_root):
        raise ValueError("Overlay output must be outside the Peglin installation directory.")


def _write_json_atomically(path: Path, document: dict[str, Any]) -> None:
    serialized = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)

    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            text=True,
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.chmod(0o644)
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def create_overlay_patch(
    terms_path: Path,
    source_manifest_path: Path,
    overrides_path: Path,
    glossary_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Validate reviewed inputs and atomically write a Korean overlay patch."""

    _, structure_issues = lint_overrides(overrides_path)
    structure_errors = [
        issue for issue in structure_issues if issue.severity == "error"
    ]
    if structure_errors:
        details = "; ".join(
            f"{issue.code}{f' [{issue.term}]' if issue.term else ''}: {issue.message}"
            for issue in structure_errors
        )
        raise ValueError(f"Override structure validation failed: {details}")

    summary, issues = validate(
        terms_path,
        glossary_path,
        overrides_path,
        source_manifest_path,
    )
    errors = [issue for issue in issues if issue.severity == "error"]
    if errors:
        details = "; ".join(
            f"{issue.code}{f' [{issue.term}]' if issue.term else ''}: {issue.message}"
            for issue in errors
        )
        raise ValueError(f"Overlay validation failed: {details}")
    if summary["staleOverrides"]:
        raise ValueError(
            f"Overlay validation failed: {summary['staleOverrides']} stale override(s)."
        )

    rows = read_terms_csv(terms_path)
    manifest = _read_source_manifest(source_manifest_path, len(rows))
    overrides = read_overrides(overrides_path)

    expected_terms = [row["Term"] for row in rows if row.get("English", "").strip()]
    if not expected_terms:
        raise ValueError("The source snapshot has no terms with English text.")
    expected_set = set(expected_terms)
    actual_set = set(overrides)
    if actual_set != expected_set:
        missing = sorted(expected_set - actual_set)
        unexpected = sorted(actual_set - expected_set)
        parts: list[str] = []
        if missing:
            parts.append(f"missing={missing!r}")
        if unexpected:
            parts.append(f"unexpected={unexpected!r}")
        raise ValueError(
            "Overrides must cover exactly every term with nonblank English: "
            + ", ".join(parts)
        )

    terms: dict[str, dict[str, str]] = {}
    any_draft = False
    rows_by_term = {row["Term"]: row for row in rows}
    for term in expected_terms:
        override = overrides[term]
        if not isinstance(override, dict):
            raise ValueError(f"Override for {term!r} must be an object.")

        translation = override.get("translation")
        status = override.get("status")
        fingerprint = override.get("sourceFingerprint")
        if not isinstance(translation, str) or not translation.strip():
            raise ValueError(f"Override for {term!r} must have a nonempty translation.")
        if not isinstance(status, str) or status not in {"draft", "approved"}:
            raise ValueError(f"Override for {term!r} has an invalid status.")
        if not isinstance(fingerprint, str) or _SHA256_PATTERN.fullmatch(fingerprint) is None:
            raise ValueError(f"Override for {term!r} must have a lowercase SHA-256 sourceFingerprint.")
        actual_fingerprint = compute_source_fingerprint(rows_by_term[term])
        if fingerprint != actual_fingerprint:
            raise ValueError(f"Override for {term!r} has a stale sourceFingerprint.")

        entry = {
            "translation": translation,
            "status": status,
            "sourceFingerprint": fingerprint,
        }
        reviewed_build_id = override.get("reviewedBuildId")
        if reviewed_build_id is not None:
            if not isinstance(reviewed_build_id, str) or not reviewed_build_id.strip():
                raise ValueError(f"Override for {term!r} has an invalid reviewedBuildId.")
            entry["reviewedBuildId"] = reviewed_build_id
        terms[term] = entry
        any_draft = any_draft or status == "draft"

    document: dict[str, Any] = {
        "schemaVersion": 1,
        "kind": "peglin-korean-overlay",
        "game": "Peglin",
        "language": "ko",
        "status": "draft" if any_draft else "approved",
        "source": {
            "steamAppId": manifest["steamAppId"],
            "steamBuildId": manifest["steamBuildId"],
            "unityVersion": manifest["unityVersion"],
            "assetSha256": manifest["assetSha256"],
        },
        "terms": terms,
    }

    _reject_unsafe_output(
        output_path,
        (terms_path, source_manifest_path, overrides_path, glossary_path),
        manifest,
    )
    _write_json_atomically(output_path, document)
    return document
