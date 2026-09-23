"""Structural and translation-safety checks for extracted rows and overrides."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .extract import CSV_FIELDS
from .fingerprints import source_fingerprint

TOKEN_PATTERN = re.compile(
    r"<[^>\r\n]+>"
    r"|\{\[[^\]\r\n]+\]\}"
    r"|\[/?[A-Za-z_][A-Za-z0-9_.:-]*(?:=[^\]\r\n]*)?\]"
    r"|\{(?:/?[A-Za-z_][A-Za-z0-9_.-]*(?:=[^{}\r\n]*)?|\d+)\}"
    r"|%(?:\d+\$)?[-+#0 ]*\d*(?:\.\d+)?[a-zA-Z%]"
)


@dataclass(frozen=True)
class Issue:
    severity: str
    code: str
    message: str
    term: str = ""


def protected_tokens(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(text)


def _markup_marker(token: str) -> tuple[str, str, bool] | None:
    if token.startswith("<") and token.endswith(">"):
        contents = token[1:-1]
        if contents.startswith("/"):
            tag_name = contents[1:]
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.:-]*", tag_name):
                return None
            return ("angle", tag_name.casefold(), True)
        contents = contents.strip()
        if contents.endswith("/"):
            return None
        if contents.startswith("#"):
            return ("angle", "color", False)
        tag_parts = contents.split("=", 1)[0].split(None, 1)
        if not tag_parts or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.:-]*", tag_parts[0]):
            return None
        tag_name = tag_parts[0].casefold()
        if tag_name == "sprite":
            return None
        return ("angle", tag_name, False)

    if token.startswith("[") and token.endswith("]"):
        contents = token[1:-1].strip()
        if contents.startswith("/"):
            return ("square", contents[1:].casefold(), True)
        if "=" not in contents:
            return ("square", contents.casefold(), False)
        return None

    if token.startswith("{") and token.endswith("}"):
        contents = token[1:-1].strip()
        if contents.startswith("/"):
            return ("brace", contents[1:].casefold(), True)
        if contents.startswith("[") or "=" in contents or contents.isdecimal():
            return None
        return ("brace", contents.casefold(), False)
    return None


def _markup_is_balanced(text: str) -> bool:
    tokens = protected_tokens(text)
    closing_markers = {
        marker[:2]
        for token in tokens
        if (marker := _markup_marker(token)) is not None and marker[2]
    }
    stack: list[tuple[str, str]] = []
    for token in tokens:
        marker = _markup_marker(token)
        if marker is None:
            if (
                token.startswith("<")
                and token.endswith(">")
                and token[1:-1].lstrip().startswith("/")
            ):
                return False
            continue
        delimiter, tag_name, is_closing = marker
        key = (delimiter, tag_name)
        if is_closing:
            if not stack or stack.pop() != key:
                return False
        elif key in closing_markers:
            stack.append(key)
    return not stack


def read_terms_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = set(reader.fieldnames or ())
        missing = set(CSV_FIELDS) - fields
        if missing:
            raise ValueError(f"CSV is missing required columns: {', '.join(sorted(missing))}")
        return [
            {key: value or "" for key, value in row.items() if key is not None}
            for row in reader
        ]


def index_terms_csv(path: Path) -> dict[str, dict[str, str]]:
    indexed: dict[str, dict[str, str]] = {}
    for row_number, row in enumerate(read_terms_csv(path), start=2):
        key = row.get("Term", "")
        if not key.strip() or key != key.strip():
            raise ValueError(f"CSV row {row_number} has an empty or padded term key.")
        if key in indexed:
            raise ValueError(f"Duplicate term key in CSV row {row_number}: {key!r}.")
        indexed[key] = row
    return indexed


def read_overrides(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Override file root must be a JSON object.")
    if data.get("schemaVersion") != 1:
        raise ValueError("Override schemaVersion must be 1.")
    terms = data.get("terms")
    if not isinstance(terms, dict):
        raise ValueError("Override file must contain a terms object.")
    return terms


def _check_translation(
    source: str, translation: str, term: str, source_name: str
) -> list[Issue]:
    if not translation:
        return []
    issues: list[Issue] = []
    expected = protected_tokens(source)
    actual = protected_tokens(translation)
    if Counter(expected) != Counter(actual):
        issues.append(
            Issue(
                "error",
                "PROTECTED_TOKEN_MISMATCH",
                f"{source_name} protected tokens differ: source={expected!r}, translation={actual!r}.",
                term,
            )
        )
    if not _markup_is_balanced(translation):
        issues.append(
            Issue(
                "error",
                "UNBALANCED_MARKUP",
                f"{source_name} has unbalanced markup tags.",
                term,
            )
        )
    if source.count("\n") != translation.count("\n"):
        issues.append(
            Issue(
                "warning",
                "LINE_BREAK_COUNT_CHANGED",
                f"{source_name} has {source.count(chr(10))} source line breaks and "
                f"{translation.count(chr(10))} translated line breaks.",
                term,
            )
        )
    return issues


def validate(
    terms_path: Path,
    glossary_path: Path | None = None,
    overrides_path: Path | None = None,
    source_manifest_path: Path | None = None,
) -> tuple[dict[str, int], list[Issue]]:
    if glossary_path is not None and not glossary_path.is_file():
        raise FileNotFoundError(f"Glossary file was not found: {glossary_path}")
    if overrides_path is not None and not overrides_path.is_file():
        raise FileNotFoundError(f"Override file was not found: {overrides_path}")

    rows = read_terms_csv(terms_path)
    issues: list[Issue] = []
    by_term: dict[str, dict[str, str]] = {}
    empty_official = 0
    identical = 0
    dev_notes = 0

    for row_number, row in enumerate(rows, start=2):
        raw_key = row.get("Term", "")
        key = raw_key.strip()
        if not key:
            issues.append(Issue("error", "EMPTY_TERM", f"CSV row {row_number} has no term key."))
            continue
        if raw_key != key:
            issues.append(Issue("error", "PADDED_TERM", "Term key has leading or trailing whitespace.", key))
            continue
        if key in by_term:
            issues.append(Issue("error", "DUPLICATE_TERM", "Term key occurs more than once.", key))
            continue
        by_term[key] = row
        english = row.get("English", "")
        official = row.get("OfficialKorean", "")
        revised = row.get("RevisedKorean", "")
        empty_official += bool(english.strip()) and not official.strip()
        identical += bool(official) and english == official
        dev_notes += bool(row.get("DevNotes", "").strip())
        issues.extend(_check_translation(english, revised, key, "RevisedKorean"))

    glossary: list[dict[str, str]] = []
    if glossary_path is not None:
        with glossary_path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            glossary_seen: set[str] = set()
            for row_number, item in enumerate(reader, start=2):
                key = (item.get("Term") or "").strip()
                preferred = (item.get("PreferredKorean") or "").strip()
                if not key or not preferred:
                    issues.append(
                        Issue("error", "INVALID_GLOSSARY_ROW", f"Glossary row {row_number} needs Term and PreferredKorean.")
                    )
                elif key in glossary_seen:
                    issues.append(Issue("error", "DUPLICATE_GLOSSARY_TERM", "Glossary term occurs more than once.", key))
                else:
                    glossary_seen.add(key)
                    glossary.append({"Term": key, "PreferredKorean": preferred})

        for row in by_term.values():
            translation = row.get("RevisedKorean", "")
            if not translation:
                continue
            for entry in glossary:
                source_term = entry["Term"]
                source_contains_term = re.search(
                    rf"(?<!\w){re.escape(source_term)}(?!\w)",
                    row.get("English", ""),
                    re.IGNORECASE,
                )
                if source_contains_term and entry["PreferredKorean"] not in translation:
                    issues.append(
                        Issue(
                            "warning",
                            "GLOSSARY_MISMATCH",
                            f"Expected glossary term {entry['PreferredKorean']!r}.",
                            row.get("Term", ""),
                        )
                    )

    override_count = 0
    stale_override_count = 0
    if overrides_path is not None:
        try:
            overrides = read_overrides(overrides_path)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            issues.append(Issue("error", "INVALID_OVERRIDES", str(exc)))
            overrides = {}

        approved_overrides = [
            (key, item)
            for key, item in overrides.items()
            if isinstance(item, dict) and item.get("status") == "approved"
        ]
        manifest_path = source_manifest_path or terms_path.with_name("source.json")
        source_build_id: str | None = None
        if approved_overrides:
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if not isinstance(manifest, dict):
                    raise ValueError("Source manifest root must be a JSON object.")
                build_id = manifest.get("steamBuildId")
                if isinstance(build_id, str) and build_id.strip():
                    source_build_id = build_id
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                issues.append(Issue("error", "SOURCE_BUILD_UNAVAILABLE", str(exc)))
            if source_build_id is None and not any(
                issue.code == "SOURCE_BUILD_UNAVAILABLE" for issue in issues
            ):
                issues.append(
                    Issue(
                        "error",
                        "SOURCE_BUILD_UNAVAILABLE",
                        f"Source manifest has no Steam build ID: {manifest_path}",
                    )
                )

        for key, item in overrides.items():
            override_count += 1
            if not isinstance(key, str) or not isinstance(item, dict):
                issues.append(Issue("error", "INVALID_OVERRIDE", "Each override must be an object.", str(key)))
                continue
            row = by_term.get(key)
            if row is None:
                issues.append(Issue("error", "UNKNOWN_OVERRIDE_TERM", "Override term is absent from this source snapshot.", key))
                continue
            translation = item.get("translation")
            status = item.get("status")
            if not isinstance(translation, str) or not translation.strip():
                issues.append(Issue("error", "EMPTY_OVERRIDE", "Override translation must be nonempty.", key))
                continue
            if not isinstance(status, str) or status not in {"draft", "approved"}:
                issues.append(Issue("error", "INVALID_OVERRIDE_STATUS", "Override status must be draft or approved.", key))
            expected_fingerprint = item.get("sourceFingerprint")
            actual_fingerprint = source_fingerprint(row)
            if not isinstance(expected_fingerprint, str):
                severity = "error" if status == "approved" else "warning"
                issues.append(Issue(severity, "OVERRIDE_UNBOUND", "Override has no sourceFingerprint.", key))
            elif expected_fingerprint != actual_fingerprint:
                stale_override_count += 1
                severity = "error" if status == "approved" else "warning"
                issues.append(Issue(severity, "OVERRIDE_STALE", "English or translator notes changed since review.", key))

            if status == "approved":
                reviewed_build_id = item.get("reviewedBuildId")
                if not isinstance(reviewed_build_id, str) or not reviewed_build_id.strip():
                    issues.append(
                        Issue(
                            "error",
                            "OVERRIDE_BUILD_UNBOUND",
                            "Approved override has no reviewedBuildId.",
                            key,
                        )
                    )
                elif source_build_id is not None and reviewed_build_id != source_build_id:
                    issues.append(
                        Issue(
                            "error",
                            "OVERRIDE_BUILD_MISMATCH",
                            f"Override was reviewed for build {reviewed_build_id!r}, "
                            f"but this snapshot is build {source_build_id!r}.",
                            key,
                        )
                    )
            issues.extend(_check_translation(row.get("English", ""), translation, key, "override"))

            for entry in glossary:
                source_term = entry["Term"]
                if re.search(rf"(?<!\w){re.escape(source_term)}(?!\w)", row.get("English", ""), re.IGNORECASE):
                    if entry["PreferredKorean"] not in translation:
                        issues.append(
                            Issue(
                                "warning",
                                "GLOSSARY_MISMATCH",
                                f"Expected glossary term {entry['PreferredKorean']!r}.",
                                key,
                            )
                        )

    summary = {
        "terms": len(rows),
        "uniqueTerms": len(by_term),
        "missingOfficialKoreanWithEnglish": int(empty_official),
        "identicalEnglishAndOfficialKorean": int(identical),
        "termsWithDevNotes": int(dev_notes),
        "nonEmptyDevNoteFields": sum(
            bool(row.get("DevNotes", "")) for row in by_term.values()
        ),
        "overrides": override_count,
        "staleOverrides": stale_override_count,
        "errors": sum(issue.severity == "error" for issue in issues),
        "warnings": sum(issue.severity == "warning" for issue in issues),
    }
    return summary, issues
