"""Build deterministic release artifacts on GitHub-hosted Linux."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import zipfile
import zlib
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .atomic_write import write_bytes_atomically
from .candidate import _PLUGIN_ARCHIVE_PATH, PLUGIN_VERSION, create_prebuilt_client_candidate
from .patching import create_locked_overlay_patch
from .release_tag import is_release_tag, validate_release_tag_status
from .source_lock import (
    DEFAULT_PLUGIN_SOURCE_INPUTS,
    RETAINED_RUNTIME_RECEIPT,
    plugin_source_inputs_sha256,
    read_source_lock,
    sha256_file,
    validate_runtime_provenance,
)
from .validation import read_translation_directory

REVISION_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}")


def _json_bytes(document: dict[str, Any]) -> bytes:
    return (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _write_footprint_report(
    report_path: Path,
    candidate_path: Path,
    overlay_path: Path,
    plugin_path: Path,
    source_lock_path: Path,
    project_root: Path,
    source_revision: str,
    source_lock: dict[str, Any],
    plugin_source_inputs: tuple[str, ...],
) -> None:
    """Record actual install-ZIP bytes without changing the seven release assets."""

    try:
        uv_result = subprocess.run(
            ["uv", "--version"], check=False, capture_output=True, text=True, timeout=5
        )
        uv_version = uv_result.stdout.strip() if uv_result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        uv_version = None

    member_rows: list[dict[str, Any]] = []
    with zipfile.ZipFile(candidate_path) as archive:
        infos = archive.infolist()
        if len(infos) != 6 or len({info.filename for info in infos}) != 6:
            raise ValueError("Candidate footprint requires exactly six unique ZIP members.")
        for info in infos:
            contents = archive.read(info)
            if len(contents) != info.file_size:
                raise ValueError(f"ZIP member length changed: {info.filename}")
            member_rows.append(
                {
                    "name": info.filename,
                    "uncompressed_bytes": info.file_size,
                    "compressed_bytes": info.compress_size,
                    "sha256": hashlib.sha256(contents).hexdigest(),
                }
            )
    by_name = {row["name"]: row for row in member_rows}
    overlay_name = "BepInEx/plugins/PeglinKoreanRevised/overlay.json"
    if _PLUGIN_ARCHIVE_PATH not in by_name or overlay_name not in by_name:
        raise ValueError("Candidate footprint is missing its plugin DLL or overlay member.")
    if by_name[_PLUGIN_ARCHIVE_PATH]["sha256"] != sha256_file(plugin_path) or by_name[overlay_name][
        "sha256"
    ] != sha256_file(overlay_path):
        raise ValueError("ZIP footprint does not match the validated DLL or standalone overlay.")
    zip_bytes = candidate_path.stat().st_size
    compressed_bytes = sum(row["compressed_bytes"] for row in member_rows)
    container_overhead = zip_bytes - compressed_bytes
    if container_overhead <= 0:
        raise ValueError("ZIP container overhead must be positive.")
    release_manifest_path = candidate_path.parent / "release-manifest.json"
    release_manifest = json.loads(release_manifest_path.read_text(encoding="utf-8"))
    if (
        release_manifest.get("sourceRevision") != source_revision
        or release_manifest.get("artifacts", {}).get(candidate_path.name)
        != sha256_file(candidate_path)
        or release_manifest.get("artifacts", {}).get(overlay_path.name) != sha256_file(overlay_path)
    ):
        raise ValueError("Candidate footprint does not match the release manifest identity.")
    uv_lock = project_root / "uv.lock"
    pyproject = project_root / "pyproject.toml"
    current_inputs_hash = plugin_source_inputs_sha256(project_root, plugin_source_inputs)
    locked_inputs_hash = source_lock["runtime"]["sourceInputsSha256"]
    retained = current_inputs_hash != locked_inputs_hash
    retention_path = project_root / RETAINED_RUNTIME_RECEIPT
    retention_receipt = json.loads(retention_path.read_text(encoding="utf-8")) if retained else None
    report = {
        "schema_version": 1,
        "source_revision": source_revision,
        "runtime_provenance": {
            "origin": "retained historical DLL" if retained else "current locked plugin inputs",
            "historical_source_revision": (
                retention_receipt["historicalSourceRevision"] if retention_receipt else None
            ),
            "locked_source_inputs_sha256": locked_inputs_hash,
            "current_source_inputs_sha256": current_inputs_hash,
            "retention_receipt_sha256": sha256_file(retention_path) if retained else None,
        },
        "source_lock_sha256": sha256_file(source_lock_path),
        "release_manifest_sha256": sha256_file(release_manifest_path),
        "uv_lock_sha256": sha256_file(uv_lock) if uv_lock.is_file() else None,
        "pyproject_sha256": sha256_file(pyproject) if pyproject.is_file() else None,
        "python_version": sys.version.split()[0],
        "uv_version": uv_version,
        "zip_compression": "DEFLATE level 9",
        "zlib_version": zlib.ZLIB_VERSION,
        "zlib_runtime_version": zlib.ZLIB_RUNTIME_VERSION,
        "install_zip": {
            "name": candidate_path.name,
            "sha256": sha256_file(candidate_path),
            "bytes": zip_bytes,
            "member_uncompressed_bytes": sum(row["uncompressed_bytes"] for row in member_rows),
            "member_compressed_bytes": compressed_bytes,
            "container_overhead_bytes": container_overhead,
            "members": member_rows,
        },
        "standalone_overlay": {
            "sha256": sha256_file(overlay_path),
            "bytes": overlay_path.stat().st_size,
            "also_in_install_zip": True,
        },
        "plugin_dll": {"sha256": sha256_file(plugin_path), "bytes": plugin_path.stat().st_size},
    }
    with report_path.open("xb") as stream:
        stream.write(_json_bytes(report))


def _assert_report_source(project_root: Path, source_revision: str) -> None:
    if re.fullmatch(r"[0-9a-f]{40}", source_revision) is None:
        raise ValueError("Footprint report requires a full lowercase source SHA.")
    try:
        head = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(project_root), "status", "--porcelain", "--untracked-files=no"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"Footprint report source could not be verified: {exc}") from exc
    if head != source_revision or dirty:
        raise ValueError("Footprint report requires the exact clean checked-out source SHA.")


def _release_notes(
    release_tag: str,
    source_revision: str,
    source_lock: dict[str, Any],
    status: str,
) -> bytes:
    review_note = (
        "This prerelease contains draft translations. Some terms and game situations have not "
        "been checked in play; complete scene coverage is not claimed. Future translation "
        "changes will follow reports from actual play.\n\n"
        if status == "draft"
        else "The translation data is approved. Approval does not imply a complete playthrough "
        "of every scene.\n\n"
    )
    release_url = "https://github.com/PiesP/peglin-korean-revised/releases/tag/" + release_tag
    changes = (
        "## Changes since rc.2\n\n"
        "- The plugin verifies and parses one snapshot of the overlay file, so a replacement "
        "during startup cannot pair parsed translations with another file's digest.\n"
        "- Startup reports a successful first application correctly when a localization "
        "callback or scene update applies translations before initial polling completes.\n"
        "- Runtime session ownership and failed-startup handling were tightened. Candidate "
        "packaging and source checks now bind the plugin and release files more strictly.\n"
        "- Translation rows, their draft review status, and supported game build are unchanged.\n\n"
        if release_tag == "peglin-ko-v1.0.0-rc.3"
        else ""
    )
    return (
        f"# Peglin Korean Revised {release_tag.removeprefix('peglin-ko-')}\n\n"
        f"- Release tag: `{release_tag}`\n"
        f"- Translation status: `{status}`\n"
        f"- Translation entries: {source_lock['translationCount']}\n"
        f"- Supported Steam build: `{source_lock['steamBuildId']}`\n"
        f"- Source revision: `{source_revision}`\n\n"
        f"{changes}"
        "The patch applies Korean translations in memory only after the supported game files "
        "match their recorded hashes. It does not modify game files.\n\n"
        "## Scope and limitations\n\n"
        f"{review_note}"
        "Only the recorded Windows game build is supported. Steam/DLC, physical GPU and audio "
        "behavior, callback-first timing in the game, and a full playthrough have not been "
        "qualified for this candidate.\n\n"
        "## Install, update, remove and rollback\n\n"
        f"Download `PeglinKoreanRevised-*.zip` from this release's [asset list]({release_url}). "
        "The auto-generated GitHub source ZIP and standalone JSON overlay are not install "
        "packages. Close the game before changing files. On update, remove only "
        "`BepInEx/plugins/PeglinKoreanRevised`, then extract the new install ZIP in the same "
        "game/profile directory. Remove that plugin directory to uninstall; keep BepInEx and "
        "its settings if other mods use them. To roll back, repeat the update steps with the "
        "prior coherent release ZIP. Do not mix files from different releases. "
        f"See the [installation guide](https://github.com/PiesP/peglin-korean-revised/blob/{release_tag}/README.md).\n\n"
        "Report translation issues through the [translation suggestion form]"
        "(https://github.com/PiesP/peglin-korean-revised/issues/new?template=translation-suggestion.yml); "
        "a proposed correction is optional. Report installation or runtime problems through "
        "the [patch problem form]"
        "(https://github.com/PiesP/peglin-korean-revised/issues/new?template=patch-problem.yml).\n"
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
    footprint_report: Path | None = None,
) -> dict[str, Path]:
    """Validate locked inputs and create deterministic public release artifacts."""

    if REVISION_PATTERN.fullmatch(source_revision) is None or ".." in source_revision:
        raise ValueError("Source revision contains unsupported characters.")
    plugin_source_inputs = tuple(plugin_source_inputs)
    if not isinstance(release_tag, str):
        raise ValueError("Release tag must be a string.")
    if not is_release_tag(release_tag):
        raise ValueError("Release tag does not use the reserved translation version format.")
    terms_path = terms_path.expanduser().resolve()
    source_lock_path = source_lock_path.expanduser().resolve()
    project_root = project_root.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if footprint_report is not None:
        footprint_report = footprint_report.expanduser().resolve()
        _assert_report_source(project_root, source_revision)
        if footprint_report == output_dir or footprint_report.is_relative_to(output_dir):
            raise ValueError("Footprint report must be outside the release output directory.")
        if not footprint_report.parent.is_dir():
            raise ValueError("Footprint report parent directory does not exist.")
        if footprint_report.exists():
            raise ValueError("Footprint report already exists.")
    if output_dir == terms_path or output_dir.is_relative_to(terms_path):
        raise ValueError("Release output must be outside the contribution CSV directory.")
    if output_dir.exists():
        raise FileExistsError(
            f"Release output already exists; choose a new directory: {output_dir}"
        )

    source_lock = read_source_lock(source_lock_path)
    plugin_path = validate_runtime_provenance(
        project_root,
        source_lock,
        plugin_source_inputs,
        package_version=PLUGIN_VERSION,
    )
    build_id = source_lock["steamBuildId"]
    asset_hash = source_lock["resourcesAssetsSha256"]
    rows = read_translation_directory(terms_path)
    expected_status = (
        "draft" if any(row["Status"] == "draft" for row in rows.values()) else "approved"
    )
    validate_release_tag_status(release_tag, expected_status)
    output_dir.mkdir()
    overlay_path = output_dir / f"peglin-ko-{build_id}-{asset_hash[:8]}.json"
    overlay = create_locked_overlay_patch(terms_path, source_lock, overlay_path)
    prerelease = validate_release_tag_status(release_tag, overlay["status"])
    candidate_path = create_prebuilt_client_candidate(
        overlay_path,
        output_dir,
        plugin_path,
        source_lock["assemblyCSharpSha256"],
        project_root,
        source_lock["runtime"]["pluginVersion"],
    )

    license_path = output_dir / "LICENSE"
    license_bytes = (project_root / "LICENSE").read_bytes()
    write_bytes_atomically(license_path, license_bytes)
    translation_notice_path = output_dir / "TRANSLATION-NOTICE.txt"
    translation_notice_bytes = (project_root / "TRANSLATION-NOTICE.txt").read_bytes()
    write_bytes_atomically(translation_notice_path, translation_notice_bytes)

    notes_path = output_dir / "release-notes.md"
    notes_bytes = _release_notes(release_tag, source_revision, source_lock, overlay["status"])
    write_bytes_atomically(notes_path, notes_bytes)

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
    write_bytes_atomically(manifest_path, _json_bytes(manifest))
    artifacts[manifest_path.name] = sha256_file(manifest_path)

    if footprint_report is not None:
        _assert_report_source(project_root, source_revision)
        _write_footprint_report(
            footprint_report,
            candidate_path,
            overlay_path,
            plugin_path,
            source_lock_path,
            project_root,
            source_revision,
            source_lock,
            plugin_source_inputs,
        )
    checksums_path = output_dir / "SHA256SUMS.txt"
    checksums = "".join(f"{digest}  {name}\n" for name, digest in sorted(artifacts.items())).encode(
        "ascii"
    )
    write_bytes_atomically(checksums_path, checksums)
    return {
        "overlay": overlay_path,
        "candidate": candidate_path,
        "license": license_path,
        "translationNotice": translation_notice_path,
        "releaseNotes": notes_path,
        "releaseManifest": manifest_path,
        "checksums": checksums_path,
    }
