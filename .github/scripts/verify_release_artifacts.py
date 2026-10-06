"""Verify downloaded release artifacts using only trusted standard-library code.

This module is inert on import. The publish job must load it from a reviewed,
immutable source commit separate from the candidate release artifacts.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import zipfile
from pathlib import Path


def verify_release_artifacts(release_dir: Path, source_sha: str, release_tag: str) -> tuple[bool, str, str]:
    """Return prerelease flag, tag and overlay name only after full validation."""
    root = release_dir
    prerelease = re.fullmatch(
        r"peglin-ko-v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)-rc\.[1-9][0-9]*",
        release_tag,
    ) is not None
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise ValueError("The source commit is not a full Git SHA.")
    if not (
        re.fullmatch(
            r"peglin-ko-v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)",
            release_tag,
        )
        or prerelease
    ):
        raise ValueError("The release tag does not use the reserved version format.")

    required = {
        "release-manifest.json",
        "release-notes.md",
        "SHA256SUMS.txt",
        "LICENSE",
        "TRANSLATION-NOTICE.txt",
    }
    if not root.is_dir() or any(not (root / name).is_file() for name in required):
        raise ValueError("The release artifact is missing required files.")

    manifest = json.loads((root / "release-manifest.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("The release manifest root is invalid.")
    if (
        manifest.get("schemaVersion") != 2
        or manifest.get("kind") != "peglin-korean-release-provenance"
    ):
        raise ValueError("The release manifest kind is invalid.")
    if manifest.get("sourceRevision") != source_sha:
        raise ValueError("The release manifest does not match the verified source commit.")
    if manifest.get("releaseTag") != release_tag:
        raise ValueError("The release manifest does not match the administrator-selected tag.")
    status = manifest.get("status")
    if status not in {"draft", "approved"}:
        raise ValueError("The translation status is invalid.")
    if manifest.get("prerelease") is not prerelease:
        raise ValueError("The release manifest prerelease flag disagrees with its version tag.")
    if (status == "draft") != prerelease:
        raise ValueError("Draft translations require an RC tag; approved translations require a stable tag.")

    checksums_path = root / "SHA256SUMS.txt"
    checksum_digests = {}
    for line in checksums_path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9._-]+)", line)
        if not match or match.group(2) in checksum_digests:
            raise ValueError("The checksum file contains an invalid or duplicate entry.")
        checksum_digests[match.group(2)] = match.group(1)
    expected = set(checksum_digests)
    if not {"release-manifest.json", "release-notes.md", "LICENSE", "TRANSLATION-NOTICE.txt"} <= expected:
        raise ValueError("The checksum file does not cover the required release files.")

    items = list(root.iterdir())
    if any(not path.is_file() or path.is_symlink() for path in items):
        raise ValueError("The release artifact contains an unexpected directory or symlink.")
    actual = {path.name for path in items if path.name != checksums_path.name}
    if actual != expected:
        raise ValueError("The release files do not match the checksum inventory.")
    for name in expected:
        contents = (root / name).read_bytes()
        if hashlib.sha256(contents).hexdigest() != checksum_digests[name]:
            raise ValueError(f"Checksum mismatch: {name}")

    manifest_artifacts = manifest.get("artifacts")
    if (
        not isinstance(manifest_artifacts, dict)
        or set(manifest_artifacts) != expected - {"release-manifest.json"}
    ):
        raise ValueError("The release manifest artifact inventory is invalid.")
    for name, digest in manifest_artifacts.items():
        if not isinstance(digest, str) or digest != checksum_digests.get(name):
            raise ValueError(f"Release manifest digest mismatch: {name}")

    overlay_files = [
        name
        for name in expected
        if name.endswith(".json") and name != "release-manifest.json"
    ]
    if len(overlay_files) != 1:
        raise ValueError("The JSON translation overlay is missing.")
    archives = [name for name in expected if name.endswith(".zip")]
    if len(archives) != 1:
        raise ValueError("The installable patch archive is missing.")

    archive_path = root / archives[0]
    expected_members = {
        "BepInEx/plugins/PeglinKoreanRevised/PeglinKoreanRevised.dll",
        "BepInEx/plugins/PeglinKoreanRevised/overlay.json",
        "BepInEx/plugins/PeglinKoreanRevised/manifest.json",
        "README.md",
        "LICENSE",
        "TRANSLATION-NOTICE.txt",
    }
    with zipfile.ZipFile(archive_path) as archive:
        members = archive.namelist()
        if len(members) != len(expected_members) or set(members) != expected_members:
            raise ValueError("The install archive contains unexpected or duplicate members.")
        if archive.testzip() is not None:
            raise ValueError("The install archive failed its CRC check.")
        package_manifest = json.loads(archive.read("BepInEx/plugins/PeglinKoreanRevised/manifest.json"))
        archive_overlay_bytes = archive.read("BepInEx/plugins/PeglinKoreanRevised/overlay.json")
        archive_license = archive.read("LICENSE")
        archive_translation_notice = archive.read("TRANSLATION-NOTICE.txt")

    overlay_path = root / overlay_files[0]
    overlay_bytes = overlay_path.read_bytes()
    overlay = json.loads(overlay_bytes)
    if archive_overlay_bytes != overlay_bytes:
        raise ValueError("Standalone overlay and install archive overlay differ.")
    if archive_license != (root / "LICENSE").read_bytes():
        raise ValueError("Install archive MIT License differs from the release notice.")
    if archive_translation_notice != (root / "TRANSLATION-NOTICE.txt").read_bytes():
        raise ValueError("Install archive translation notice differs from the release notice.")

    if package_manifest.get("kind") != "peglin-korean-client-candidate":
        raise ValueError("The install archive manifest kind is invalid.")
    if (
        manifest.get("game") != "Peglin"
        or manifest.get("steamAppId") != "1296610"
        or manifest.get("language") != "ko"
        or overlay.get("kind") != "peglin-korean-overlay"
        or overlay.get("game") != manifest.get("game")
        or overlay.get("language") != manifest.get("language")
        or package_manifest.get("game") != manifest.get("game")
        or package_manifest.get("steamAppId") != manifest.get("steamAppId")
        or package_manifest.get("language") != manifest.get("language")
        or package_manifest.get("source") != overlay.get("source")
    ):
        raise ValueError("Game, language, or source metadata disagrees across release files.")
    overlay_terms = overlay.get("terms")
    if (
        not isinstance(overlay_terms, dict)
        or not overlay_terms
        or len(overlay_terms) != manifest.get("translationCount")
        or package_manifest.get("translationCount") != len(overlay_terms)
    ):
        raise ValueError("Translation counts disagree across release files.")
    source = manifest.get("source")
    overlay_source = overlay.get("source")
    package_runtime = package_manifest.get("runtime")
    if (
        not isinstance(source, dict)
        or not isinstance(overlay_source, dict)
        or not isinstance(package_runtime, dict)
        or overlay_source.get("steamAppId") != manifest.get("steamAppId")
        or source.get("steamBuildId") != overlay_source.get("steamBuildId")
        or source.get("unityVersion") != overlay_source.get("unityVersion")
        or source.get("resourcesAssetsSha256") != overlay_source.get("assetSha256")
        or source.get("assemblyCSharpSha256") != package_runtime.get("assemblyCSharpSha256")
    ):
        raise ValueError("Peglin source metadata disagrees across release files.")
    package_files = package_manifest.get("files")
    expected_hashes = {
        "BepInEx/plugins/PeglinKoreanRevised/PeglinKoreanRevised.dll",
        "BepInEx/plugins/PeglinKoreanRevised/overlay.json",
    }
    if not isinstance(package_files, dict) or set(package_files) != expected_hashes:
        raise ValueError("The install archive manifest file inventory is invalid.")
    with zipfile.ZipFile(archive_path) as archive:
        for name, digest in package_files.items():
            if not isinstance(digest, str) or hashlib.sha256(archive.read(name)).hexdigest() != digest:
                raise ValueError(f"Install archive manifest hash mismatch: {name}")
    if overlay.get("status") != status or package_manifest.get("status") != status:
        raise ValueError("Translation status disagrees across release files.")
    runtime = manifest.get("runtime")
    if (
        not isinstance(runtime, dict)
        or runtime.get("pluginVersion") != package_runtime.get("pluginVersion")
        or runtime.get("sha256") != package_files.get(
            "BepInEx/plugins/PeglinKoreanRevised/PeglinKoreanRevised.dll"
        )
    ):
        raise ValueError("Runtime metadata disagrees across release files.")
    return prerelease, release_tag, overlay_files[0]


def main() -> int:
    try:
        prerelease, release_tag, overlay_name = verify_release_artifacts(
            Path(os.environ["RELEASE_DIR"]),
            os.environ["SOURCE_SHA"],
            os.environ["RELEASE_TAG"],
        )
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write(f"prerelease={'true' if prerelease else 'false'}\n")
            output.write(f"tag={release_tag}\n")
            output.write(f"overlay={overlay_name}\n")
    except (ValueError, OSError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
