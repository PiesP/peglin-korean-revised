"""Build an installable BepInEx candidate from a source-bound JSON overlay."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


_BUILD_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,64}")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_PLUGIN_GUID = "piesp.peglin.koreanrevised"
_PLUGIN_VERSION = "0.1.2"
_PLUGIN_ARCHIVE_PATH = "BepInEx/plugins/PeglinKoreanRevised/PeglinKoreanRevised.dll"
_PEGLIN_BEPINEX_PACK_VERSION = "5.4.2100"
_BEPINEX_VERSION = "5.4.21"
_ZIP_FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_ZIP_TIMESTAMP_EPOCH = datetime(1980, 1, 1)
_ZIP_TIMESTAMP_END = datetime(2108, 1, 1)
_ZIP_TIMESTAMP_RESOLUTION_SECONDS = 2


def _run_dotnet(command: list[str], project_dir: Path) -> None:
    try:
        result = subprocess.run(
            command,
            cwd=project_dir,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise ValueError(f"Could not run the .NET SDK: {exc}") from exc

    if result.returncode != 0:
        output = "\n".join(
            line
            for line in (result.stdout + "\n" + result.stderr).splitlines()
            if line.strip()
        )
        tail = "\n".join(output.splitlines()[-80:])
        raise ValueError(
            f"Plugin build command failed with exit code {result.returncode}:\n{tail}"
        )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _candidate_readme(
    overlay: dict[str, Any],
    plugin_hash: str,
    assembly_sha256: str,
) -> str:
    source = overlay["source"]
    review_note = (
        "This draft translation has not received in-game review.\n"
        if overlay["status"] == "draft"
        else "The translation entries are approved, but this package has not been verified in-game.\n"
    )
    return (
        "# Peglin Korean Revised candidate\n\n"
        "This is an installable BepInEx plugin candidate generated from the "
        "Peglin I2 Localization table.\n\n"
        "## Requirements\n\n"
        "- Peglin for Windows with the exact source build listed below.\n"
        "- BepInEx Mono. The Peglin community pack currently listed on "
        "[Thunderstore](https://thunderstore.io/c/peglin/p/BepInEx/"
        "BepInExPack_Peglin/) is version "
        f"{_PEGLIN_BEPINEX_PACK_VERSION} (BepInEx {_BEPINEX_VERSION}).\n\n"
        "## Install\n\n"
        "1. Close Peglin.\n"
        "2. Install the Peglin BepInEx pack using Thunderstore Mod Manager, "
        "r2modman, or its manual instructions.\n"
        "3. If BepInEx/config/BepInEx.cfg does not exist yet, run Peglin once "
        "with BepInEx installed, then close it. Open the config and, in "
        "[Preloader.Entrypoint], "
        "set Type = MonoBehaviour. Keep Assembly = UnityEngine.CoreModule.dll "
        "and Method = .cctor, and preserve the rest of the file. The inspected "
        "Peglin setup uses Application as the entrypoint; that can run plugin "
        "Awake before Unity ticks MonoBehaviours, leaving Start and coroutines "
        "inactive.\n"
        "4. Extract this archive into the Peglin installation directory, the "
        "folder containing Peglin.exe.\n"
        "5. Start the game with BepInEx enabled and select Korean in the game "
        "language settings.\n\n"
        "To uninstall this candidate, close the game and remove "
        "BepInEx/plugins/PeglinKoreanRevised/.\n\n"
        "## Candidate details\n\n"
        f"- Translation status: **{overlay['status']}**\n"
        f"- Translated terms: **{len(overlay['terms'])}**\n"
        f"- Steam build: **{source['steamBuildId']}**\n"
        f"- Unity version: **{source['unityVersion']}**\n"
        f"- resources.assets SHA-256: {source['assetSha256']}\n"
        f"- Assembly-CSharp.dll SHA-256: {assembly_sha256}\n"
        f"- Plugin SHA-256: {plugin_hash}\n\n"
        "At startup the plugin verifies the installed resources.assets hash "
        "and the Assembly-CSharp.dll hash synchronously before waiting for "
        "localization data. It refuses to apply "
        "this candidate when either hash differs. It writes translations only "
        "to Peglin's in-memory I2 Korean language table and refreshes localized "
        "UI text; it does not write to the game installation. A later game "
        "update requires a newly generated candidate.\n\n"
        f"{review_note}"
    )


def _zip_timestamp_for_contents(
    contents: bytes,
) -> tuple[int, int, int, int, int, int]:
    """Return a reproducible DOS-compatible timestamp derived from file content."""

    # ZIP DOS timestamps have two-second resolution. Reserve the epoch used by
    # previous packages, then derive this file's time from its content.
    timestamp_slots = int(
        (_ZIP_TIMESTAMP_END - _ZIP_TIMESTAMP_EPOCH).total_seconds()
        // _ZIP_TIMESTAMP_RESOLUTION_SECONDS
    )
    digest = hashlib.sha256(contents).digest()
    timestamp_slot = (
        int.from_bytes(digest, byteorder="big") % (timestamp_slots - 1)
    ) + 1
    timestamp = _ZIP_TIMESTAMP_EPOCH + timedelta(
        seconds=timestamp_slot * _ZIP_TIMESTAMP_RESOLUTION_SECONDS
    )
    return (
        timestamp.year,
        timestamp.month,
        timestamp.day,
        timestamp.hour,
        timestamp.minute,
        timestamp.second,
    )


def _write_zip_atomically(path: Path, files: dict[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        with zipfile.ZipFile(
            temporary_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for name, contents in sorted(files.items()):
                date_time = (
                    _zip_timestamp_for_contents(contents)
                    if name == _PLUGIN_ARCHIVE_PATH
                    else _ZIP_FIXED_TIMESTAMP
                )
                info = zipfile.ZipInfo(name, date_time=date_time)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(
                    info,
                    contents,
                    compress_type=zipfile.ZIP_DEFLATED,
                    compresslevel=9,
                )
        temporary_path.chmod(0o644)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _read_overlay(path: Path) -> dict[str, Any]:
    try:
        overlay = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read overlay JSON: {exc}") from exc
    if not isinstance(overlay, dict) or overlay.get("kind") != "peglin-korean-overlay":
        raise ValueError("Overlay must be a Peglin Korean JSON overlay.")
    if overlay.get("game") != "Peglin" or overlay.get("language") != "ko":
        raise ValueError("Overlay must target Peglin and Korean (ko).")

    source = overlay.get("source")
    terms = overlay.get("terms")
    if not isinstance(source, dict) or not isinstance(terms, dict) or not terms:
        raise ValueError("Overlay source metadata and translation terms are required.")
    build_id = source.get("steamBuildId")
    asset_sha256 = source.get("assetSha256")
    if not isinstance(build_id, str) or _BUILD_ID_PATTERN.fullmatch(build_id) is None:
        raise ValueError("Overlay source steamBuildId is invalid.")
    if not isinstance(asset_sha256, str) or _SHA256_PATTERN.fullmatch(asset_sha256) is None:
        raise ValueError("Overlay source assetSha256 is invalid.")
    if overlay.get("status") not in {"draft", "approved"}:
        raise ValueError("Overlay status must be draft or approved.")
    return overlay


def _package_candidate(
    overlay_path: Path,
    candidate_dir: Path,
    plugin_dll: Path,
    assembly_sha256: str,
) -> Path:
    overlay = _read_overlay(overlay_path)
    if not plugin_dll.is_file():
        raise ValueError(f"Plugin DLL does not exist: {plugin_dll}")
    if _SHA256_PATTERN.fullmatch(assembly_sha256) is None:
        raise ValueError("Assembly-CSharp.dll hash must be a lowercase SHA-256 digest.")

    source = overlay["source"]
    terms = overlay["terms"]
    overlay_bytes = overlay_path.read_bytes()
    plugin_bytes = plugin_dll.read_bytes()
    overlay_sha256 = hashlib.sha256(overlay_bytes).hexdigest()
    plugin_sha256 = hashlib.sha256(plugin_bytes).hexdigest()
    package_manifest = {
        "schemaVersion": 1,
        "kind": "peglin-korean-client-candidate",
        "game": "Peglin",
        "steamAppId": "1296610",
        "language": "ko",
        "status": overlay["status"],
        "translationCount": len(terms),
        "source": source,
        "runtime": {
            "engine": "Unity Mono",
            "i2Localization": "I2.Loc",
            "loader": "BepInEx Mono",
            "minimumBepInExVersion": _BEPINEX_VERSION,
            "recommendedPeglinPack": f"BepInExPack_Peglin {_PEGLIN_BEPINEX_PACK_VERSION}",
            "pluginGuid": _PLUGIN_GUID,
            "pluginVersion": _PLUGIN_VERSION,
            "assemblyCSharpSha256": assembly_sha256,
        },
        "files": {
            _PLUGIN_ARCHIVE_PATH: plugin_sha256,
            "BepInEx/plugins/PeglinKoreanRevised/overlay.json": overlay_sha256,
        },
    }
    manifest_bytes = (
        json.dumps(package_manifest, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    readme_bytes = _candidate_readme(
        overlay,
        plugin_sha256,
        assembly_sha256,
    ).encode("utf-8")
    build_id = source["steamBuildId"]
    asset_sha256 = source["assetSha256"]
    archive_path = candidate_dir / (
        f"PeglinKoreanRevised-{build_id}-{asset_sha256[:8]}.zip"
    )
    _write_zip_atomically(
        archive_path,
        {
            _PLUGIN_ARCHIVE_PATH: plugin_bytes,
            "BepInEx/plugins/PeglinKoreanRevised/overlay.json": overlay_bytes,
            "BepInEx/plugins/PeglinKoreanRevised/manifest.json": manifest_bytes,
            "README.md": readme_bytes,
        },
    )
    return archive_path


def create_prebuilt_client_candidate(
    overlay_path: Path,
    candidate_dir: Path,
    plugin_dll: Path,
    assembly_sha256: str,
) -> Path:
    """Package a verified tracked plugin without an installed Peglin copy."""

    return _package_candidate(
        overlay_path.expanduser().resolve(),
        candidate_dir.expanduser().resolve(),
        plugin_dll.expanduser().resolve(),
        assembly_sha256,
    )


def create_client_candidate(
    overlay_path: Path,
    game_root: Path,
    candidate_dir: Path,
    plugin_project: Path,
    dotnet: str = "dotnet",
) -> Path:
    """Compile the plugin against the installed game and package an install ZIP."""

    overlay_path = overlay_path.expanduser().resolve()
    game_root = game_root.expanduser().resolve()
    candidate_dir = candidate_dir.expanduser().resolve()
    plugin_project = plugin_project.expanduser().resolve()
    managed_dir = game_root / "Peglin_Data" / "Managed"
    game_asset = game_root / "Peglin_Data" / "resources.assets"
    game_assembly = managed_dir / "Assembly-CSharp.dll"
    if not overlay_path.is_file():
        raise ValueError(f"Overlay JSON does not exist: {overlay_path}")
    if not game_assembly.is_file():
        raise ValueError(f"Peglin managed assemblies were not found: {managed_dir}")
    if not game_asset.is_file():
        raise ValueError(f"Peglin resources.assets was not found: {game_asset}")
    if not plugin_project.is_file():
        raise ValueError(f"BepInEx plugin project does not exist: {plugin_project}")
    if plugin_project.is_relative_to(game_root):
        raise ValueError(
            "Plugin project and its build output must be outside the Peglin installation directory."
        )
    if candidate_dir == game_root or candidate_dir.is_relative_to(game_root):
        raise ValueError("Candidate output must be outside the Peglin installation directory.")

    overlay = _read_overlay(overlay_path)
    source = overlay["source"]
    build_id = source.get("steamBuildId")
    asset_sha256 = source.get("assetSha256")
    if not isinstance(build_id, str) or _BUILD_ID_PATTERN.fullmatch(build_id) is None:
        raise ValueError("Overlay source steamBuildId is invalid.")
    if not isinstance(asset_sha256, str) or _SHA256_PATTERN.fullmatch(asset_sha256) is None:
        raise ValueError("Overlay source assetSha256 is invalid.")
    installed_asset_sha256 = _sha256_file(game_asset)
    if installed_asset_sha256 != asset_sha256:
        raise ValueError(
            "Overlay source asset hash does not match the installed Peglin resources.assets."
        )
    installed_assembly_sha256 = _sha256_file(game_assembly)

    project_dir = plugin_project.parent
    package_config = project_dir / "NuGet.Config"
    lock_file = project_dir / "packages.lock.json"
    if not package_config.is_file():
        raise ValueError(f"NuGet package source configuration is missing: {package_config}")
    if not lock_file.is_file():
        raise ValueError(
            f"NuGet lock file is missing: {lock_file}; restore once and commit the generated lock file."
        )

    property_argument = f"-p:PeglinManagedDir={managed_dir}"
    _run_dotnet(
        [
            dotnet,
            "restore",
            str(plugin_project),
            "--locked-mode",
            "--configfile",
            str(package_config),
            property_argument,
            "--nologo",
        ],
        project_dir,
    )
    _run_dotnet(
        [
            dotnet,
            "build",
            str(plugin_project),
            "--no-restore",
            "--configuration",
            "Release",
            "--verbosity",
            "minimal",
            "--nologo",
            property_argument,
            "-p:ContinuousIntegrationBuild=true",
        ],
        project_dir,
    )

    plugin_dll = project_dir / "bin" / "Release" / "net46" / "PeglinKoreanRevised.dll"
    if not plugin_dll.is_file():
        raise ValueError(f"Plugin build did not produce its DLL: {plugin_dll}")

    if _sha256_file(game_asset) != installed_asset_sha256:
        raise ValueError("Peglin resources.assets changed while building the client candidate.")
    if _sha256_file(game_assembly) != installed_assembly_sha256:
        raise ValueError("Peglin Assembly-CSharp.dll changed while building the client candidate.")

    return _package_candidate(
        overlay_path,
        candidate_dir,
        plugin_dll,
        installed_assembly_sha256,
    )
