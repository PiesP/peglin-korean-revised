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
PLUGIN_VERSION = "0.1.2"
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


def _candidate_readme(overlay: dict[str, Any]) -> str:
    review_note = (
        "번역 상태: 초안입니다. 일부 문구는 게임 화면에서 검토되지 않았을 수 있습니다.\n\n"
        if overlay["status"] == "draft"
        else "번역 문구는 승인 상태입니다. 이 패치 전체가 모든 게임 화면에서 검수되었다는 뜻은 아닙니다.\n\n"
    )
    return (
        "# 페글린 한국어 번역 패치\n\n"
        "개발 과정에서 AI 도구의 도움을 받았습니다.\n\n"
        "## 설치\n\n"
        "1. Peglin을 종료합니다.\n"
        "2. [Peglin용 BepInEx 팩](https://thunderstore.io/c/peglin/p/"
        "BepInEx/BepInExPack_Peglin/)을 설치합니다. 수동 설치라면 압축을 푼 뒤 "
        "`BepInExPack_Peglin` 폴더 안의 파일과 폴더를 `Peglin.exe`가 있는 곳으로 "
        "옮깁니다. 모드 매니저 사용자는 선택한 Peglin 프로필에 팩을 설치합니다.\n"
        "3. 게임을 한 번 실행한 다음 종료합니다. `BepInEx/config/BepInEx.cfg`를 "
        "메모장으로 엽니다. 모드 매니저를 사용한다면 프로필 안의 같은 경로에 있는 "
        "파일을 엽니다. `[Preloader.Entrypoint]` 항목의 `Type` 값을 "
        "`MonoBehaviour`로 바꿉니다. 나머지 설정은 그대로 둡니다.\n\n"
        "   ```ini\n"
        "   Type = MonoBehaviour\n"
        "   ```\n\n"
        "4. 이 ZIP 파일을 `Peglin.exe`가 있는 폴더에 풉니다. 모드 매니저를 "
        "사용한다면 선택한 Peglin 프로필 폴더에 설치하고 게임도 매니저에서 "
        "실행합니다.\n"
        "5. 게임을 실행하고 언어 설정에서 한국어를 선택합니다.\n\n"
        "## 수동 설치 후 폴더 구조\n\n"
        "아래는 주요 경로만 표시한 예시입니다. 게임과 BepInEx 팩의 다른 파일 및 "
        "폴더는 생략했습니다. 패치 ZIP에 들어 있는 안내와 라이선스 파일은 게임 "
        "폴더 바로 아래에 함께 풀립니다.\n\n"
        "```text\n"
        "Peglin/                              (Peglin.exe가 있는 게임 폴더)\n"
        "├── Peglin.exe\n"
        "├── BepInEx/\n"
        "│   ├── config/\n"
        "│   │   └── BepInEx.cfg\n"
        "│   └── plugins/\n"
        "│       └── PeglinKoreanRevised/\n"
        "│           ├── PeglinKoreanRevised.dll\n"
        "│           ├── overlay.json\n"
        "│           └── manifest.json\n"
        "├── winhttp.dll                      (BepInEx 팩)\n"
        "├── doorstop_config.ini              (BepInEx 팩)\n"
        "├── doorstop_libs/                   (BepInEx 팩)\n"
        "├── README.md                        (패치 설치 안내)\n"
        "├── LICENSE\n"
        "└── TRANSLATION-NOTICE.txt\n"
        "```\n\n"
        "업데이트하려면 게임을 종료하고 `BepInEx/plugins/"
        "PeglinKoreanRevised` 폴더를 삭제한 뒤 최신 ZIP을 같은 위치에 풉니다.\n"
        "제거할 때는 게임을 종료한 다음 같은 폴더를 삭제합니다.\n\n"
        "게임 업데이트 후 번역이 나오지 않으면 [릴리스 목록]("
        "https://github.com/PiesP/peglin-korean-revised/releases)에서 최신 패치를 "
        "확인하세요. 설치나 실행 문제가 계속되면 [패치 문제 제보]("
        "https://github.com/PiesP/peglin-korean-revised/issues/new?template="
        "patch-problem.yml)를 이용해 주세요.\n\n"
        "## 번역 상태\n\n"
        f"{review_note}"
        "## 라이선스\n\n"
        "프로젝트 코드와 도구에는 MIT 라이선스가 적용됩니다. 번역 자료는 MIT "
        "범위에 포함되지 않습니다. 함께 제공된 LICENSE와 TRANSLATION-NOTICE.txt를 "
        "확인해 주세요.\n"
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
    project_root: Path,
) -> Path:
    overlay = _read_overlay(overlay_path)
    if not plugin_dll.is_file():
        raise ValueError(f"Plugin DLL does not exist: {plugin_dll}")
    if _SHA256_PATTERN.fullmatch(assembly_sha256) is None:
        raise ValueError("Assembly-CSharp.dll hash must be a lowercase SHA-256 digest.")
    try:
        license_bytes = (project_root / "LICENSE").read_bytes()
        translation_notice_bytes = (project_root / "TRANSLATION-NOTICE.txt").read_bytes()
    except OSError as exc:
        raise ValueError(f"Could not read distribution license notices: {exc}") from exc

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
            "pluginVersion": PLUGIN_VERSION,
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
    readme_bytes = _candidate_readme(overlay).encode("utf-8")
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
            "LICENSE": license_bytes,
            "TRANSLATION-NOTICE.txt": translation_notice_bytes,
        },
    )
    return archive_path


def create_prebuilt_client_candidate(
    overlay_path: Path,
    candidate_dir: Path,
    plugin_dll: Path,
    assembly_sha256: str,
    project_root: Path,
) -> Path:
    """Package a verified tracked plugin without an installed Peglin copy."""

    return _package_candidate(
        overlay_path.expanduser().resolve(),
        candidate_dir.expanduser().resolve(),
        plugin_dll.expanduser().resolve(),
        assembly_sha256,
        project_root.expanduser().resolve(),
    )


def create_client_candidate(
    overlay_path: Path,
    game_root: Path,
    candidate_dir: Path,
    plugin_project: Path,
    dotnet: str = "dotnet",
    project_root: Path | None = None,
) -> Path:
    """Compile the plugin against the installed game and package an install ZIP."""

    overlay_path = overlay_path.expanduser().resolve()
    game_root = game_root.expanduser().resolve()
    candidate_dir = candidate_dir.expanduser().resolve()
    plugin_project = plugin_project.expanduser().resolve()
    project_root = (
        project_root.expanduser().resolve()
        if project_root is not None
        else Path(__file__).resolve().parents[2]
    )
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
        project_root,
    )
