"""Build deterministic release artifacts on GitHub-hosted Linux."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .candidate import PLUGIN_VERSION, create_prebuilt_client_candidate
from .patching import create_locked_overlay_patch
from .release_tag import is_release_tag, validate_release_tag_status
from .source_lock import (
    DEFAULT_PLUGIN_SOURCE_INPUTS,
    read_source_lock,
    sha256_file,
    validate_runtime_provenance,
)


REVISION_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}")


def _write_bytes_atomically(path: Path, contents: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.chmod(0o644)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _json_bytes(document: dict[str, Any]) -> bytes:
    return (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _release_notes(
    release_tag: str,
    source_revision: str,
    source_lock: dict[str, Any],
    status: str,
) -> bytes:
    return (
        f"# Peglin Korean Revised {release_tag.removeprefix('peglin-ko-')}\n\n"
        f"- 릴리스 태그: `{release_tag}`\n"
        f"- 번역 상태: `{status}`\n"
        f"- 번역 항목: {source_lock['translationCount']}개\n"
        f"- 대상 Steam 빌드: `{source_lock['steamBuildId']}`\n"
        f"- 소스 리비전: `{source_revision}`\n\n"
        "이 패치는 게임 파일을 직접 수정하지 않으며, 대상 게임 파일의 해시가 "
        "일치할 때만 메모리에서 한국어 번역을 적용합니다.\n"
    ).encode("utf-8")


def build_release_candidate(
    terms_path: Path,
    source_lock_path: Path,
    project_root: Path,
    source_revision: str,
    output_dir: Path,
    *,
    release_tag: str,
    plugin_source_inputs: Iterable[str] = DEFAULT_PLUGIN_SOURCE_INPUTS,
) -> dict[str, Path]:
    """Validate locked inputs and create deterministic public release artifacts."""

    if REVISION_PATTERN.fullmatch(source_revision) is None or ".." in source_revision:
        raise ValueError("Source revision contains unsupported characters.")
    if not isinstance(release_tag, str):
        raise ValueError("Release tag must be a string.")
    if not is_release_tag(release_tag):
        raise ValueError("Release tag does not use the reserved translation version format.")
    terms_path = terms_path.expanduser().resolve()
    source_lock_path = source_lock_path.expanduser().resolve()
    project_root = project_root.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if output_dir == terms_path or output_dir.is_relative_to(terms_path):
        raise ValueError("Release output must be outside the contribution CSV directory.")

    source_lock = read_source_lock(source_lock_path)
    plugin_path = validate_runtime_provenance(
        project_root,
        source_lock,
        plugin_source_inputs,
        package_version=PLUGIN_VERSION,
    )
    build_id = source_lock["steamBuildId"]
    asset_hash = source_lock["resourcesAssetsSha256"]
    overlay_path = output_dir / f"peglin-ko-{build_id}-{asset_hash[:8]}.json"
    overlay = create_locked_overlay_patch(terms_path, source_lock, overlay_path)
    prerelease = validate_release_tag_status(release_tag, overlay["status"])
    candidate_path = create_prebuilt_client_candidate(
        overlay_path,
        output_dir,
        plugin_path,
        source_lock["assemblyCSharpSha256"],
        project_root,
    )

    license_path = output_dir / "LICENSE"
    license_bytes = (project_root / "LICENSE").read_bytes()
    _write_bytes_atomically(license_path, license_bytes)
    translation_notice_path = output_dir / "TRANSLATION-NOTICE.txt"
    translation_notice_bytes = (project_root / "TRANSLATION-NOTICE.txt").read_bytes()
    _write_bytes_atomically(translation_notice_path, translation_notice_bytes)

    notes_path = output_dir / "release-notes.md"
    notes_bytes = _release_notes(
        release_tag, source_revision, source_lock, overlay["status"]
    )
    _write_bytes_atomically(notes_path, notes_bytes)

    artifacts = {
        overlay_path.name: sha256_file(overlay_path),
        candidate_path.name: sha256_file(candidate_path),
        license_path.name: hashlib.sha256(license_bytes).hexdigest(),
        translation_notice_path.name: hashlib.sha256(translation_notice_bytes).hexdigest(),
        notes_path.name: hashlib.sha256(notes_bytes).hexdigest(),
    }
    manifest = {
        "schemaVersion": 2,
        "kind": "peglin-korean-release-provenance",
        "game": "Peglin",
        "steamAppId": source_lock["steamAppId"],
        "language": "ko",
        "sourceRevision": source_revision,
        "releaseTag": release_tag,
        "status": overlay["status"],
        "prerelease": prerelease,
        "translationCount": source_lock["translationCount"],
        "source": {
            "steamBuildId": build_id,
            "unityVersion": source_lock["unityVersion"],
            "resourcesAssetsSha256": asset_hash,
            "assemblyCSharpSha256": source_lock["assemblyCSharpSha256"],
        },
        "runtime": source_lock["runtime"],
        "artifacts": dict(sorted(artifacts.items())),
    }
    manifest_path = output_dir / "release-manifest.json"
    _write_bytes_atomically(manifest_path, _json_bytes(manifest))
    artifacts[manifest_path.name] = sha256_file(manifest_path)

    checksums_path = output_dir / "SHA256SUMS.txt"
    checksums = "".join(
        f"{digest}  {name}\n" for name, digest in sorted(artifacts.items())
    ).encode("ascii")
    _write_bytes_atomically(checksums_path, checksums)
    return {
        "overlay": overlay_path,
        "candidate": candidate_path,
        "license": license_path,
        "translationNotice": translation_notice_path,
        "releaseNotes": notes_path,
        "releaseManifest": manifest_path,
        "checksums": checksums_path,
    }
