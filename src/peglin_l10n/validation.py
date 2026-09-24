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
from .source_lock import read_source_lock

TOKEN_PATTERN = re.compile(
    r"<[^>\r\n]+>"
    r"|\{\[[^\]\r\n]+\]\}"
    r"|\[/?[A-Za-z_][A-Za-z0-9_.:-]*(?:=[^\]\r\n]*)?\]"
    r"|\{(?:/?[A-Za-z_][A-Za-z0-9_.-]*(?:=[^{}\r\n]*)?|\d+)\}"
    # A space flag needs a delimiter after its conversion to avoid matching prose like "% of".
    r"|%(?:\d+\$)?[-+#0]*\d*(?:\.\d+)?[a-zA-Z%]"
    r"|%(?:\d+\$)?[-+#0 ]*\d*(?:\.\d+)?[a-zA-Z%](?![a-zA-Z])"
)

TRANSLATION_FIELDS = (
    "Term",
    "Translation",
    "Status",
    "ReviewedBuildId",
    "Comment",
)

_HIT_STYLE_ACTIVATION = re.compile(
    r"<style=hit>[^<>\r\n]*활성화[^<>\r\n]*</style>"
)
_ORB_VARIABLE_WITH_FIXED_PARTICLE = re.compile(
    r"\[(?:var|variable)=[^\]\r\n]*orb[^\]\r\n]*\]"
    r"(?:</style>)?\s*"
    r"(?P<particle>이라고|라고|이라는|라는|"
    r"으로|로|은|는|이|가|을|를|과|와)(?![가-힣])",
    re.IGNORECASE,
)
_MALFORMED_SPRITE_NAME_TOKEN = re.compile(
    r'<sprite\b[^>]*\bname="[^"]*>', re.IGNORECASE
)

# Keep this list explicit. Similar-looking *_name terms do not imply that two
# translated names refer to the same in-game entity.
_CANONICAL_NAME_EXPECTATIONS = {
    "Enemies/slime_painbow_name": "페인보우 슬라임드롭",
    "Enemies/slime_rainbow_name": "무지개 슬라임드롭",
    "Achievements/NEW_ACHIEVEMENT_16_48_DESC": "페인보우 슬라임드롭",
    "Challenges/taste_the_painbow_desc": "페인보우 슬라임드롭",
    "Enemies/slime_painbow_lore": "무지개 슬라임드롭",
}


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
    vertexp_open_count = 0
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
        # The game's vertexp text effect can close inside a rich-text style tag.
        # Check its opening and closing tags as a pair without imposing stack order.
        if key == ("brace", "vertexp"):
            if is_closing:
                if vertexp_open_count == 0:
                    return False
                vertexp_open_count -= 1
            else:
                vertexp_open_count += 1
            continue
        if is_closing:
            if not stack or stack.pop() != key:
                return False
        elif key in closing_markers:
            stack.append(key)
    return not stack and vertexp_open_count == 0


def _glossary_term_occurs(source_term: str, text: str) -> bool:
    """Match whole glossary terms without splitting hyphenated game names."""
    return re.search(
        rf"(?<![\w-]){re.escape(source_term)}(?![\w-])",
        text,
        re.IGNORECASE,
    ) is not None


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


def read_translation_directory(path: Path) -> dict[str, dict[str, str]]:
    """Read public contribution CSVs without loading proprietary source text."""

    if not path.is_dir():
        raise ValueError(f"Translation terms directory was not found: {path}")
    csv_paths = sorted(path.glob("*.csv"))
    if not csv_paths:
        raise ValueError(f"Translation terms directory contains no CSV files: {path}")
    terms: dict[str, dict[str, str]] = {}
    for csv_path in csv_paths:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if tuple(reader.fieldnames or ()) != TRANSLATION_FIELDS:
                raise ValueError(
                    f"{csv_path.name} must contain the exact columns: "
                    + ", ".join(TRANSLATION_FIELDS)
                )
            for row_number, row in enumerate(reader, start=2):
                if None in row:
                    raise ValueError(f"{csv_path.name} row {row_number} has extra columns.")
                normalized = {field: row.get(field) or "" for field in TRANSLATION_FIELDS}
                term = normalized["Term"]
                if not term.strip() or term != term.strip():
                    raise ValueError(
                        f"{csv_path.name} row {row_number} has an empty or padded term key."
                    )
                if term in terms:
                    raise ValueError(f"Duplicate term key in contribution CSVs: {term!r}.")
                normalized["_file"] = csv_path.name
                terms[term] = normalized
    return terms


def _translation_rows_as_overrides(path: Path) -> dict[str, Any]:
    rows = read_translation_directory(path)
    lock = read_source_lock(path.parent / "source-lock.json")
    lock_terms = lock["terms"]
    overrides: dict[str, Any] = {}
    for term, row in rows.items():
        metadata = lock_terms.get(term)
        entry: dict[str, str] = {
            "translation": row["Translation"],
            "status": row["Status"],
        }
        if isinstance(metadata, dict) and isinstance(metadata.get("sourceFingerprint"), str):
            entry["sourceFingerprint"] = metadata["sourceFingerprint"]
        if row["ReviewedBuildId"]:
            entry["reviewedBuildId"] = row["ReviewedBuildId"]
        if row["Comment"]:
            entry["comment"] = row["Comment"]
        overrides[term] = entry
    return overrides


def read_overrides(path: Path) -> dict[str, Any]:
    if path.is_dir():
        return _translation_rows_as_overrides(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Override file root must be a JSON object.")
    if data.get("schemaVersion") != 1:
        raise ValueError("Override schemaVersion must be 1.")
    terms = data.get("terms")
    if not isinstance(terms, dict):
        raise ValueError("Override file must contain a terms object.")
    return terms


def lint_overrides(path: Path) -> tuple[dict[str, int], list[Issue]]:
    """Check tracked override metadata without requiring a local game snapshot."""
    if path.is_dir():
        lock = read_source_lock(path.parent / "source-lock.json")
        return validate_locked_translations(path, lock)
    data = json.loads(path.read_text(encoding="utf-8"))
    issues: list[Issue] = []
    if not isinstance(data, dict):
        issues.append(
            Issue("error", "INVALID_OVERRIDES", "Override file root must be a JSON object.")
        )
        return {"overrides": 0, "draft": 0, "approved": 0, "errors": 1}, issues

    if type(data.get("schemaVersion")) is not int or data.get("schemaVersion") != 1:
        issues.append(
            Issue("error", "INVALID_SCHEMA_VERSION", "Override schemaVersion must be 1.")
        )
    if data.get("game") != "Peglin":
        issues.append(Issue("error", "INVALID_GAME", "Override game must be Peglin."))
    if data.get("language") != "ko":
        issues.append(Issue("error", "INVALID_LANGUAGE", "Override language must be ko."))

    terms = data.get("terms")
    if not isinstance(terms, dict):
        issues.append(
            Issue("error", "INVALID_TERMS", "Override file must contain a terms object.")
        )
        terms = {}
    elif not terms:
        issues.append(
            Issue("error", "EMPTY_OVERRIDES", "Override terms object must not be empty.")
        )

    status_counts = {"draft": 0, "approved": 0}
    for key, item in terms.items():
        term = key if isinstance(key, str) else str(key)
        if not isinstance(key, str) or not key.strip() or key != key.strip():
            issues.append(
                Issue(
                    "error",
                    "INVALID_TERM_KEY",
                    "Override term keys must be nonempty strings without surrounding whitespace.",
                    term,
                )
            )
            continue
        if not isinstance(item, dict):
            issues.append(
                Issue("error", "INVALID_OVERRIDE", "Each override must be an object.", term)
            )
            continue
        translation = item.get("translation")
        if not isinstance(translation, str) or not translation.strip():
            issues.append(
                Issue("error", "EMPTY_OVERRIDE", "Override translation must be nonempty.", term)
            )
        status = item.get("status")
        if not isinstance(status, str) or status not in status_counts:
            issues.append(
                Issue(
                    "error",
                    "INVALID_OVERRIDE_STATUS",
                    "Override status must be draft or approved.",
                    term,
                )
            )
        else:
            status_counts[status] += 1
        fingerprint = item.get("sourceFingerprint")
        if not isinstance(fingerprint, str) or re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None:
            issues.append(
                Issue(
                    "error",
                    "INVALID_OVERRIDE_FINGERPRINT",
                    "Override sourceFingerprint must be a lowercase SHA-256 hex digest.",
                    term,
                )
            )
        reviewed_build = item.get("reviewedBuildId")
        if reviewed_build is not None and (
            not isinstance(reviewed_build, str) or not reviewed_build.strip()
        ):
            issues.append(
                Issue(
                    "error",
                    "INVALID_OVERRIDE_BUILD_ID",
                    "Override reviewedBuildId must be a nonempty string when present.",
                    term,
                )
            )
        if status == "approved" and (
            not isinstance(reviewed_build, str) or not reviewed_build.strip()
        ):
            issues.append(
                Issue(
                    "error",
                    "OVERRIDE_BUILD_UNBOUND",
                    "Approved override has no reviewedBuildId.",
                    term,
                )
            )
        comment = item.get("comment")
        if comment is not None and not isinstance(comment, str):
            issues.append(
                Issue(
                    "error",
                    "INVALID_OVERRIDE_COMMENT",
                    "Override comment must be a string when present.",
                    term,
                )
            )

    summary = {
        "overrides": len(terms),
        "draft": status_counts["draft"],
        "approved": status_counts["approved"],
        "errors": sum(issue.severity == "error" for issue in issues),
    }
    return summary, issues


def validate_locked_translations(
    terms_path: Path,
    source_lock: dict[str, Any],
) -> tuple[dict[str, int], list[Issue]]:
    """Validate public contribution CSVs solely against safe locked metadata."""

    rows = read_translation_directory(terms_path)
    lock_terms = source_lock.get("terms")
    if not isinstance(lock_terms, dict):
        raise ValueError("Source lock terms must be an object.")
    issues: list[Issue] = []
    expected_keys = set(lock_terms)
    actual_keys = set(rows)
    for term in sorted(expected_keys - actual_keys):
        issues.append(
            Issue(
                "error",
                "MISSING_TRANSLATION_TERM",
                "Locked term is missing from contribution CSVs.",
                term,
            )
        )
    for term in sorted(actual_keys - expected_keys):
        issues.append(
            Issue(
                "error",
                "UNKNOWN_TRANSLATION_TERM",
                "Contribution term is absent from the source lock.",
                term,
            )
        )

    referenced_files: set[str] = set()
    status_counts = {"draft": 0, "approved": 0}
    for term in sorted(expected_keys & actual_keys):
        row = rows[term]
        metadata = lock_terms[term]
        if not isinstance(metadata, dict):
            issues.append(
                Issue(
                    "error",
                    "INVALID_LOCKED_TERM",
                    "Locked term metadata is invalid.",
                    term,
                )
            )
            continue
        expected_file = metadata.get("file")
        if isinstance(expected_file, str):
            referenced_files.add(expected_file)
        if row["_file"] != expected_file:
            issues.append(
                Issue(
                    "error",
                    "TRANSLATION_FILE_MISMATCH",
                    f"Term must remain in {expected_file!r}.",
                    term,
                )
            )
        fingerprint = metadata.get("sourceFingerprint")
        if (
            not isinstance(fingerprint, str)
            or re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None
        ):
            issues.append(
                Issue(
                    "error",
                    "INVALID_LOCKED_FINGERPRINT",
                    "Locked source fingerprint is invalid.",
                    term,
                )
            )
        translation = row["Translation"]
        if not translation.strip():
            issues.append(
                Issue("error", "EMPTY_OVERRIDE", "Translation must be nonempty.", term)
            )
        status = row["Status"]
        if status not in status_counts:
            issues.append(
                Issue(
                    "error",
                    "INVALID_OVERRIDE_STATUS",
                    "Status must be draft or approved.",
                    term,
                )
            )
        else:
            status_counts[status] += 1
        reviewed_build = row["ReviewedBuildId"]
        if status == "approved" and not reviewed_build:
            issues.append(
                Issue(
                    "error",
                    "OVERRIDE_BUILD_UNBOUND",
                    "Approved translation has no ReviewedBuildId.",
                    term,
                )
            )
        elif status == "approved" and reviewed_build != source_lock.get("steamBuildId"):
            issues.append(
                Issue(
                    "error",
                    "OVERRIDE_BUILD_MISMATCH",
                    f"Approved translation must be reviewed for build {source_lock.get('steamBuildId')!r}.",
                    term,
                )
            )
        expected_tokens = metadata.get("protectedTokens")
        if not isinstance(expected_tokens, list):
            issues.append(
                Issue(
                    "error",
                    "INVALID_LOCKED_TOKENS",
                    "Locked protected tokens are invalid.",
                    term,
                )
            )
        elif Counter(expected_tokens) != Counter(protected_tokens(translation)):
            issues.append(
                Issue(
                    "error",
                    "PROTECTED_TOKEN_MISMATCH",
                    "Translation protected tokens differ: "
                    f"source={expected_tokens!r}, "
                    f"translation={protected_tokens(translation)!r}.",
                    term,
                )
            )
        if translation and not _markup_is_balanced(translation):
            issues.append(
                Issue(
                    "error",
                    "UNBALANCED_MARKUP",
                    "Translation has unbalanced markup tags.",
                    term,
                )
            )

        if _HIT_STYLE_ACTIVATION.search(translation):
            issues.append(
                Issue(
                    "warning",
                    "HIT_STYLE_TERM_COLLISION",
                    "A Hit-styled phrase contains '활성화'; review the distinction "
                    "between Hit and Activate.",
                    term,
                )
            )

        if row["_file"] == "dialogue-system.csv":
            particle_matches = list(
                _ORB_VARIABLE_WITH_FIXED_PARTICLE.finditer(translation)
            )
            if particle_matches:
                particles = ", ".join(
                    sorted({match.group("particle") for match in particle_matches})
                )
                issues.append(
                    Issue(
                        "warning",
                        "FIXED_ORB_NAME_PARTICLE",
                        f"Orb-name variable is followed by a fixed Korean particle "
                        f"({particles}); rewrite the phrase or review runtime "
                        "particle handling.",
                        term,
                    )
                )

        expected_name = _CANONICAL_NAME_EXPECTATIONS.get(term)
        if expected_name is not None and expected_name not in translation:
            issues.append(
                Issue(
                    "warning",
                    "CANONICAL_NAME_DRIFT",
                    f"This reviewed reference expects the canonical Korean name "
                    f"{expected_name!r}; compare the source context before "
                    "changing it.",
                    term,
                )
            )

    for term, metadata in lock_terms.items():
        if not isinstance(metadata, dict):
            continue
        protected = metadata.get("protectedTokens")
        if not isinstance(protected, list):
            continue
        for token in protected:
            if isinstance(token, str) and _MALFORMED_SPRITE_NAME_TOKEN.fullmatch(
                token
            ):
                issues.append(
                    Issue(
                        "warning",
                        "MALFORMED_LOCKED_SPRITE_TAG",
                        f"Source lock preserves malformed sprite token "
                        f"{token!r}; review the source and rendering before "
                        "changing the translation.",
                        term,
                    )
                )

    actual_files = {path.name for path in terms_path.glob("*.csv")}
    for file_name in sorted(actual_files - referenced_files):
        issues.append(
            Issue(
                "error",
                "UNEXPECTED_TRANSLATION_FILE",
                f"CSV is not referenced by the source lock: {file_name}",
            )
        )
    for file_name in sorted(referenced_files - actual_files):
        issues.append(
            Issue(
                "error",
                "MISSING_TRANSLATION_FILE",
                f"Locked CSV is missing: {file_name}",
            )
        )

    return {
        "overrides": len(rows),
        "draft": status_counts["draft"],
        "approved": status_counts["approved"],
        "errors": sum(issue.severity == "error" for issue in issues),
        "warnings": sum(issue.severity == "warning" for issue in issues),
    }, issues


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
    if overrides_path is not None and not overrides_path.exists():
        raise FileNotFoundError(f"Translation input was not found: {overrides_path}")

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
                source_contains_term = _glossary_term_occurs(
                    source_term, row.get("English", "")
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
                if _glossary_term_occurs(source_term, row.get("English", "")):
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
