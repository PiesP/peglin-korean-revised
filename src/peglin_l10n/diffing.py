"""Compare versioned Peglin source snapshots and report review work."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .fingerprints import source_fingerprint
from .validation import index_terms_csv, read_overrides

COMPARE_FIELDS = {
    "English": "SOURCE_CHANGED",
    "DevNotes": "DEV_NOTES_CHANGED",
    "I2Description": "I2_DESCRIPTION_CHANGED",
    "OfficialKorean": "OFFICIAL_KO_CHANGED",
    "Category": "CATEGORY_CHANGED",
}


def compare_snapshots(
    old_path: Path,
    new_path: Path,
    overrides_path: Path | None = None,
) -> dict[str, Any]:
    old_rows = index_terms_csv(old_path)
    new_rows = index_terms_csv(new_path)
    overrides = read_overrides(overrides_path) if overrides_path is not None else {}

    changes: list[dict[str, Any]] = []
    counts: dict[str, int] = {
        "NEW": 0,
        "REMOVED": 0,
        **{status: 0 for status in COMPARE_FIELDS.values()},
        "OVERRIDE_STALE": 0,
        "OVERRIDE_UNBOUND": 0,
        "OVERRIDE_TERM_REMOVED": 0,
        "OVERRIDE_TERM_ORPHAN": 0,
        "UNCHANGED": 0,
    }
    for key in sorted(old_rows.keys() | new_rows.keys() | overrides.keys()):
        old = old_rows.get(key)
        new = new_rows.get(key)
        statuses: list[str] = []
        field_changes: dict[str, dict[str, str]] = {}
        if old is None and new is None:
            pass
        elif old is None:
            statuses.append("NEW")
        elif new is None:
            statuses.append("REMOVED")
        else:
            for field, status in COMPARE_FIELDS.items():
                if old.get(field, "") != new.get(field, ""):
                    statuses.append(status)
                    field_changes[field] = {"old": old.get(field, ""), "new": new.get(field, "")}

        if key in overrides:
            override = overrides[key]
            if new is None:
                status = "OVERRIDE_TERM_REMOVED" if old is not None else "OVERRIDE_TERM_ORPHAN"
                statuses.append(status)
            else:
                fingerprint = override.get("sourceFingerprint") if isinstance(override, dict) else None
                if not isinstance(fingerprint, str):
                    statuses.append("OVERRIDE_UNBOUND")
                elif fingerprint != source_fingerprint(new):
                    statuses.append("OVERRIDE_STALE")

        if not statuses:
            counts["UNCHANGED"] += 1
            continue
        for status in statuses:
            counts[status] = counts.get(status, 0) + 1
        changes.append(
            {
                "term": key,
                "statuses": statuses,
                "fieldChanges": field_changes,
                "newSourceFingerprint": source_fingerprint(new) if new is not None else None,
            }
        )

    return {
        "schemaVersion": 1,
        "oldSnapshot": str(old_path.resolve()),
        "newSnapshot": str(new_path.resolve()),
        "summary": counts,
        "changes": changes,
    }
