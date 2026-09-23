"""Read the installed Peglin I2 table without changing game files."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import struct
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import __version__

DEFAULT_GAME_ROOT = Path(
    "/mnt/c/Program Files (x86)/Steam/steamapps/common/Peglin"
)
APP_ID = "1296610"
TARGET_OBJECT_NAME = "I2Languages"
TARGET_SCRIPT = ("I2.Loc", "LanguageSourceAsset")
MAX_TERM_COUNT = 50_000
MAX_LANGUAGE_COUNT = 64
MAX_STRING_BYTES = 4_000_000
CSV_FIELDS = (
    "Term",
    "Category",
    "English",
    "DevNotes",
    "I2Description",
    "OfficialKorean",
    "RevisedKorean",
    "Status",
    "Comment",
)


class ExtractionError(ValueError):
    """Raised when the installed asset does not match the supported layout."""


@dataclass(frozen=True)
class Language:
    name: str
    code: str
    flags: int


@dataclass(frozen=True)
class Term:
    key: str
    term_type: int
    translations: tuple[str, ...]
    touch_flags: bytes
    description: str


@dataclass(frozen=True)
class ParsedTable:
    terms: tuple[Term, ...]
    languages: tuple[Language, ...]
    vector_offset: int
    vector_end: int
    language_tail_end: int


@dataclass(frozen=True)
class InstallationData:
    game_root: Path
    asset_path: Path
    build_id: str | None
    unity_version: str
    asset_sha256: str
    unitypy_version: str
    table: ParsedTable


def _align4(offset: int) -> int:
    return (offset + 3) & ~3


def _read_u32(data: bytes, offset: int, label: str) -> tuple[int, int]:
    if offset < 0 or offset + 4 > len(data):
        raise ExtractionError(f"Unexpected end of I2 data while reading {label}.")
    return struct.unpack_from("<I", data, offset)[0], offset + 4


def _read_aligned_string(
    data: bytes, offset: int, label: str
) -> tuple[str, int]:
    length, offset = _read_u32(data, offset, f"{label} length")
    if length > MAX_STRING_BYTES:
        raise ExtractionError(f"Implausible {label} length: {length} bytes.")
    end = offset + length
    if end > len(data):
        raise ExtractionError(f"Unexpected end of I2 data in {label}.")
    try:
        value = data[offset:end].decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ExtractionError(f"Invalid UTF-8 in {label} at 0x{offset:x}.") from exc
    aligned_end = _align4(end)
    if aligned_end > len(data):
        raise ExtractionError(f"Unexpected end of I2 data after {label} padding.")
    if any(data[end:aligned_end]):
        raise ExtractionError(f"Nonzero alignment bytes after {label} at 0x{end:x}.")
    return value, aligned_end


def _read_aligned_bool(data: bytes, offset: int, label: str) -> tuple[int, int]:
    if offset < 0 or offset + 4 > len(data):
        raise ExtractionError(f"Unexpected end of I2 data while reading {label}.")
    value = data[offset]
    if value not in (0, 1):
        raise ExtractionError(f"Invalid boolean value for {label}: {value}.")
    if any(data[offset + 1 : offset + 4]):
        raise ExtractionError(f"Nonzero alignment bytes after {label}.")
    return value, offset + 4


def _parse_term(data: bytes, offset: int, expected_languages: int | None) -> tuple[Term, int]:
    key, offset = _read_aligned_string(data, offset, "term key")
    if not key:
        raise ExtractionError("The I2 term table contains an empty key.")

    term_type, offset = _read_u32(data, offset, f"term type for {key!r}")
    if term_type > 255:
        raise ExtractionError(f"Implausible term type for {key!r}: {term_type}.")

    language_count, offset = _read_u32(data, offset, f"language count for {key!r}")
    if not 1 <= language_count <= MAX_LANGUAGE_COUNT:
        raise ExtractionError(
            f"Implausible language count for {key!r}: {language_count}."
        )
    if expected_languages is not None and language_count != expected_languages:
        raise ExtractionError(
            f"Inconsistent language count for {key!r}: "
            f"{language_count} instead of {expected_languages}."
        )

    translations: list[str] = []
    for index in range(language_count):
        value, offset = _read_aligned_string(
            data, offset, f"translation {index} for {key!r}"
        )
        translations.append(value)

    touch_count, offset = _read_u32(data, offset, f"flag count for {key!r}")
    if touch_count != language_count:
        raise ExtractionError(
            f"Touch flag count for {key!r} is {touch_count}; "
            f"expected {language_count}."
        )
    end_flags = offset + touch_count
    if end_flags > len(data):
        raise ExtractionError(f"Unexpected end of touch flags for {key!r}.")
    touch_flags = data[offset:end_flags]
    if any(value not in (0, 1) for value in touch_flags):
        raise ExtractionError(f"Invalid touch flag value for {key!r}.")
    offset = _align4(end_flags)
    if offset > len(data) or any(data[end_flags:offset]):
        raise ExtractionError(f"Invalid alignment after touch flags for {key!r}.")

    description, offset = _read_aligned_string(data, offset, f"description for {key!r}")
    return Term(
        key=key,
        term_type=term_type,
        translations=tuple(translations),
        touch_flags=touch_flags,
        description=description,
    ), offset


def _parse_language_tail(
    data: bytes, offset: int, expected_languages: int
) -> tuple[tuple[Language, ...], int]:
    _case_insensitive, offset = _read_aligned_bool(
        data, offset, "CaseInsensitiveTerms"
    )
    _missing_translation_policy, offset = _read_u32(
        data, offset, "OnMissingTranslation"
    )
    _term_app_name, offset = _read_aligned_string(data, offset, "mTerm_AppName")
    language_count, offset = _read_u32(data, offset, "I2 language descriptor count")
    if language_count != expected_languages:
        raise ExtractionError(
            "Language descriptor count does not match term translations "
            f"({language_count} != {expected_languages})."
        )

    languages: list[Language] = []
    for index in range(language_count):
        name, offset = _read_aligned_string(data, offset, f"language {index} name")
        code, offset = _read_aligned_string(data, offset, f"language {index} code")
        flags, offset = _read_aligned_bool(data, offset, f"language {index} flags")
        if not name:
            raise ExtractionError(f"Language descriptor {index} has no name.")
        languages.append(Language(name=name, code=code, flags=flags))

    codes = [language.code.casefold() for language in languages if language.code]
    if codes.count("en") != 1 or codes.count("ko") != 1:
        raise ExtractionError("The I2 table must have exactly one English and Korean slot.")
    if sum(language.name.strip().casefold() == "dev notes" for language in languages) != 1:
        raise ExtractionError("The I2 table must have exactly one Dev Notes slot.")
    if len(set(codes)) != len(codes):
        raise ExtractionError("The I2 language table contains duplicate language codes.")
    return tuple(languages), offset


def _parse_vector_candidate(data: bytes, count_offset: int) -> ParsedTable:
    term_count, offset = _read_u32(data, count_offset, "term vector count")
    if not 100 <= term_count <= MAX_TERM_COUNT:
        raise ExtractionError(f"Implausible I2 term count: {term_count}.")

    terms: list[Term] = []
    seen: set[str] = set()
    language_count: int | None = None
    for _ in range(term_count):
        term, offset = _parse_term(data, offset, language_count)
        if term.key in seen:
            raise ExtractionError(f"Duplicate term key: {term.key!r}.")
        seen.add(term.key)
        terms.append(term)
        if language_count is None:
            language_count = len(term.translations)

    if language_count is None:
        raise ExtractionError("The I2 term vector is empty.")
    vector_end = offset
    languages, language_tail_end = _parse_language_tail(data, offset, language_count)
    if language_tail_end + 4 > len(data):
        raise ExtractionError("The I2 source configuration suffix is missing.")
    if not any(data[language_tail_end:]):
        raise ExtractionError("The I2 source configuration suffix is empty.")

    return ParsedTable(
        terms=tuple(terms),
        languages=languages,
        vector_offset=count_offset,
        vector_end=vector_end,
        language_tail_end=language_tail_end,
    )


def parse_i2_language_table(data: bytes, mono_header_size: int) -> ParsedTable:
    """Find and validate the I2 term vector without fixed offsets or key anchors."""
    first_candidate = _align4(mono_header_size)
    candidates: list[ParsedTable] = []
    for count_offset in range(first_candidate, len(data) - 4, 4):
        term_count = struct.unpack_from("<I", data, count_offset)[0]
        if not 100 <= term_count <= MAX_TERM_COUNT:
            continue
        try:
            first, next_offset = _parse_term(data, count_offset + 4, None)
            if term_count > 1:
                _second, _ = _parse_term(data, next_offset, len(first.translations))
            candidates.append(_parse_vector_candidate(data, count_offset))
        except ExtractionError:
            continue

    if len(candidates) != 1:
        raise ExtractionError(
            "Could not identify one unambiguous I2 term vector "
            f"(validated candidates: {len(candidates)})."
        )
    return candidates[0]


def _stat_signature(stat: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        stat.st_dev,
        stat.st_ino,
        stat.st_size,
        stat.st_mtime_ns,
        stat.st_ctime_ns,
    )


def _read_asset_snapshot(asset_path: Path) -> tuple[bytes, str, tuple[int, int, int, int, int]]:
    try:
        path_before = _stat_signature(asset_path.stat())
        with asset_path.open("rb") as stream:
            descriptor_before = _stat_signature(os.fstat(stream.fileno()))
            if descriptor_before != path_before:
                raise ExtractionError("resources.assets was replaced before it could be read.")
            data = stream.read()
            descriptor_after = _stat_signature(os.fstat(stream.fileno()))
        path_after_read = _stat_signature(asset_path.stat())
    except OSError as exc:
        raise ExtractionError(f"Could not read resources.assets: {exc}") from exc

    if not data or len(data) != path_before[2]:
        raise ExtractionError("resources.assets changed or was truncated while being read.")
    if descriptor_after != path_before or path_after_read != path_before:
        raise ExtractionError("resources.assets changed while being read.")
    return data, hashlib.sha256(data).hexdigest(), path_before


def _steam_build_id(game_root: Path) -> str | None:
    manifest = game_root.parent.parent / f"appmanifest_{APP_ID}.acf"
    if not manifest.is_file():
        return None
    contents = manifest.read_text(encoding="utf-8", errors="replace")
    match = re.search(r'"buildid"\s+"(\d+)"', contents, flags=re.IGNORECASE)
    return match.group(1) if match else None


def load_installation(game_root: Path) -> InstallationData:
    game_root = game_root.expanduser().resolve()
    asset_path = game_root / "Peglin_Data" / "resources.assets"
    if not asset_path.is_file():
        raise ExtractionError(f"Peglin resources.assets was not found: {asset_path}")
    asset_bytes, source_sha256, asset_signature = _read_asset_snapshot(asset_path)
    build_id = _steam_build_id(game_root)

    try:
        import UnityPy
    except ImportError as exc:
        raise ExtractionError("UnityPy is missing; run `uv sync` in the project.") from exc

    try:
        asset_stream = io.BytesIO(asset_bytes)
        asset_stream.name = str(asset_path)
        environment = UnityPy.load(asset_stream, path=str(asset_path.parent))
    except Exception as exc:  # UnityPy exposes several parser exception types.
        raise ExtractionError(f"UnityPy could not read {asset_path}: {exc}") from exc

    matches: list[tuple[Any, Any]] = []
    for obj in environment.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        try:
            header = obj.parse_monobehaviour_head()
        except Exception:
            continue
        if getattr(header, "m_Name", None) == TARGET_OBJECT_NAME:
            matches.append((obj, header))

    if len(matches) != 1:
        raise ExtractionError(
            f"Expected one {TARGET_OBJECT_NAME} MonoBehaviour, found {len(matches)}."
        )

    obj, header = matches[0]
    try:
        script = header.m_Script.deref_parse_as_object()
    except Exception as exc:
        raise ExtractionError("Could not resolve the I2Languages MonoScript.") from exc
    actual_script = (script.m_Namespace, script.m_ClassName)
    if actual_script != TARGET_SCRIPT:
        raise ExtractionError(
            "I2Languages points to an unexpected script: "
            f"{actual_script[0]}.{actual_script[1]}"
        )

    try:
        raw = obj.get_raw_data()
        mono_header_size = _mono_header_size(
            raw, obj.assets_file.header.version, TARGET_OBJECT_NAME
        )
        table = parse_i2_language_table(raw, mono_header_size)
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError(f"Could not parse the I2 language table: {exc}") from exc

    try:
        current_asset_signature = _stat_signature(asset_path.stat())
    except OSError as exc:
        raise ExtractionError(f"Could not verify resources.assets after extraction: {exc}") from exc
    if current_asset_signature != asset_signature:
        raise ExtractionError("resources.assets changed during extraction; no snapshot was written.")
    if _steam_build_id(game_root) != build_id:
        raise ExtractionError("Steam's Peglin build manifest changed during extraction.")

    unity_version = getattr(obj.assets_file, "unity_version", "unknown")
    return InstallationData(
        game_root=game_root,
        asset_path=asset_path,
        build_id=build_id,
        unity_version=str(unity_version),
        asset_sha256=source_sha256,
        unitypy_version=UnityPy.__version__,
        table=table,
    )


def _language_index(languages: tuple[Language, ...], code: str) -> int:
    matches = [index for index, language in enumerate(languages) if language.code.casefold() == code]
    if len(matches) != 1:
        raise ExtractionError(f"Expected one {code!r} language slot; found {len(matches)}.")
    return matches[0]


def _mono_header_size(data: bytes, serialized_version: int, object_name: str) -> int:
    pointer_size = 12 if serialized_version >= 14 else 8
    name_offset = pointer_size + 4 + pointer_size
    name_length, name_data_offset = _read_u32(
        data, name_offset, "MonoBehaviour name length"
    )
    if name_length > 1024 or name_data_offset + name_length > len(data):
        raise ExtractionError("The MonoBehaviour name field is outside the object data.")
    try:
        stored_name = data[name_data_offset : name_data_offset + name_length].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ExtractionError("The MonoBehaviour name is not valid UTF-8.") from exc
    if stored_name != object_name:
        raise ExtractionError(
            f"MonoBehaviour header did not contain the expected name {object_name!r}."
        )
    header_end = _align4(name_data_offset + name_length)
    if any(data[name_data_offset + name_length : header_end]):
        raise ExtractionError("The MonoBehaviour name has nonzero alignment bytes.")
    return header_end


def _make_csv_rows(table: ParsedTable) -> list[dict[str, str]]:
    english_index = _language_index(table.languages, "en")
    korean_index = _language_index(table.languages, "ko")
    notes_index = next(
        index
        for index, language in enumerate(table.languages)
        if language.name.strip().casefold() == "dev notes"
    )
    rows: list[dict[str, str]] = []
    for term in table.terms:
        english = term.translations[english_index]
        official_korean = term.translations[korean_index]
        rows.append(
            {
                "Term": term.key,
                "Category": term.key.split("/", 1)[0] if "/" in term.key else "General",
                "English": english,
                "DevNotes": term.translations[notes_index],
                "I2Description": term.description,
                "OfficialKorean": official_korean,
                "RevisedKorean": "",
                "Status": (
                    "missing"
                    if english.strip() and not official_korean.strip()
                    else "unreviewed"
                ),
                "Comment": "",
            }
        )
    return rows


def _source_manifest(data: InstallationData) -> dict[str, Any]:
    table = data.table
    english_index = _language_index(table.languages, "en")
    korean_index = _language_index(table.languages, "ko")
    notes_index = next(
        index
        for index, language in enumerate(table.languages)
        if language.name.strip().casefold() == "dev notes"
    )
    missing_korean = sum(
        bool(term.translations[english_index].strip())
        and not term.translations[korean_index].strip()
        for term in table.terms
    )
    return {
        "schemaVersion": 1,
        "game": "Peglin",
        "steamAppId": APP_ID,
        "steamBuildId": data.build_id,
        "unityVersion": data.unity_version,
        "assetPath": str(data.asset_path),
        "assetSha256": data.asset_sha256,
        "extractedAtUtc": datetime.now(UTC).isoformat(),
        "extractorVersion": __version__,
        "unityPyVersion": data.unitypy_version,
        "termCount": len(table.terms),
        "languageCount": len(table.languages),
        "missingKoreanWithEnglish": missing_korean,
        "devNotesNonemptyCount": sum(
            bool(term.translations[notes_index]) for term in table.terms
        ),
        "devNotesNonblankCount": sum(
            bool(term.translations[notes_index].strip()) for term in table.terms
        ),
        "languages": [
            {"name": language.name, "code": language.code, "flags": language.flags}
            for language in table.languages
        ],
        "rawOffsets": {
            "termVectorCount": f"0x{table.vector_offset:x}",
            "termVectorEnd": f"0x{table.vector_end:x}",
            "languageTailEnd": f"0x{table.language_tail_end:x}",
        },
    }


def snapshot_csv_bytes(data: InstallationData) -> bytes:
    """Serialize the current installation's extracted rows deterministically."""
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(_make_csv_rows(data.table))
    return stream.getvalue().encode("utf-8")


def write_snapshot(data: InstallationData, output_dir: Path) -> Path:
    output_dir = output_dir.expanduser().resolve()
    if output_dir.exists():
        raise ExtractionError(f"Output directory already exists; refusing to overwrite: {output_dir}")

    manifest = _source_manifest(data)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary_dir = Path(
        tempfile.mkdtemp(prefix=f".{output_dir.name}-", dir=output_dir.parent)
    )
    try:
        (temporary_dir / "terms.csv").write_bytes(snapshot_csv_bytes(data))
        (temporary_dir / "source.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.rename(temporary_dir, output_dir)
    except Exception:
        if temporary_dir.exists():
            shutil.rmtree(temporary_dir)
        raise
    return output_dir


def default_output_dir(data: InstallationData) -> Path:
    build_part = f"build-{data.build_id}" if data.build_id else f"build-unknown-{data.asset_sha256[:8]}"
    return Path(__file__).resolve().parents[2] / "extracted" / build_part
