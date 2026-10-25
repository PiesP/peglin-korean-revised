"""Repackage a qualified client ZIP as an experimental local manager candidate."""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
import zlib
from importlib.resources import files
from pathlib import Path
from typing import Any

from .candidate import PLUGIN_VERSION, _write_zip_atomically

PACKAGE_VERSION = "0.1.2"
_PREFIX = "BepInEx/plugins/PeglinKoreanRevised/"
_DLL = _PREFIX + "PeglinKoreanRevised.dll"
_OVERLAY = _PREFIX + "overlay.json"
_INTEGRITY = _PREFIX + "manifest.json"
_INPUT_LIMIT = 2 * 1024 * 1024
_MEMBER_LIMITS = {
    _DLL: 1024 * 1024,
    _OVERLAY: 1024 * 1024,
    _INTEGRITY: 64 * 1024,
    "README.md": 64 * 1024,
    "LICENSE": 64 * 1024,
    "TRANSLATION-NOTICE.txt": 64 * 1024,
}
_SOURCE = {
    "steamAppId": "1296610",
    "steamBuildId": "22988052",
    "unityVersion": "2022.3.62f2",
    "assetSha256": "6625e7db90be3fbe28f207ee2b5ecebe95c3011e68a40002af10db98f23fbeb2",
}
_ASSEMBLY_SHA256 = "bf5af951bf16373f507c30af068ccc92aa867affbe6e855decf82486c2dc6244"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _digest(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()


def _read_json(contents: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(contents.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid {label} JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object.")
    return value


def _read_qualified_input(input_zip: Path, expected_sha256: str) -> dict[str, bytes]:
    if _SHA256.fullmatch(expected_sha256) is None:
        raise ValueError("Expected input ZIP SHA-256 must be a lowercase 64-digit hex digest.")
    try:
        if input_zip.stat().st_size > _INPUT_LIMIT:
            raise ValueError("Input ZIP exceeds the size limit.")
        contents = input_zip.read_bytes()
    except OSError as exc:
        raise ValueError(f"Could not read input ZIP: {exc}") from exc
    if len(contents) > _INPUT_LIMIT:
        raise ValueError("Input ZIP exceeds the size limit.")
    if _digest(contents) != expected_sha256:
        raise ValueError("Input ZIP SHA-256 does not match the required qualification anchor.")

    try:
        with zipfile.ZipFile(io.BytesIO(contents)) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if len(names) != len(_MEMBER_LIMITS) or set(names) != set(_MEMBER_LIMITS):
                raise ValueError("Input ZIP must contain exactly the six expected files once each.")
            result = {}
            for entry in entries:
                limit = _MEMBER_LIMITS[entry.filename]
                if (
                    entry.is_dir()
                    or entry.flag_bits & 1
                    or entry.file_size > limit
                    or entry.compress_size > _INPUT_LIMIT
                    or (entry.external_attr >> 16) & 0o170000 not in (0, 0o100000)
                ):
                    raise ValueError(f"Unsafe or oversized input ZIP member: {entry.filename}")
                with archive.open(entry) as source:
                    data = source.read(limit + 1)
                if len(data) != entry.file_size or len(data) > limit:
                    raise ValueError(f"Input ZIP member exceeds its size limit: {entry.filename}")
                result[entry.filename] = data
    except (
        OSError,
        EOFError,
        NotImplementedError,
        RuntimeError,
        zlib.error,
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
    ) as exc:
        raise ValueError(f"Invalid input ZIP or member CRC: {exc}") from exc
    return result


def _validate_candidate(contents: dict[str, bytes]) -> None:
    manifest = _read_json(contents[_INTEGRITY], "plugin integrity manifest")
    overlay = _read_json(contents[_OVERLAY], "overlay")
    for label, value, kind in (
        ("Plugin integrity manifest", manifest, "peglin-korean-client-candidate"),
        ("Overlay", overlay, "peglin-korean-overlay"),
    ):
        if (
            type(value.get("schemaVersion")) is not int
            or value["schemaVersion"] != 1
            or value.get("kind") != kind
            or value.get("game") != "Peglin"
            or value.get("language") != "ko"
            or value.get("status") != "draft"
            or value.get("source") != _SOURCE
        ):
            raise ValueError(f"{label} is not the supported draft Peglin build.")
    terms = overlay.get("terms")
    if not isinstance(terms, dict) or len(terms) != 1899:
        raise ValueError("Overlay must contain the supported 1899 draft terms.")
    if (
        manifest.get("steamAppId") != "1296610"
        or manifest.get("translationCount") != len(terms)
        or manifest.get("files")
        != {_DLL: _digest(contents[_DLL]), _OVERLAY: _digest(contents[_OVERLAY])}
    ):
        raise ValueError("Plugin integrity manifest does not match the packaged files.")
    runtime = manifest.get("runtime")
    if not isinstance(runtime, dict) or (
        runtime.get("pluginGuid") != "piesp.peglin.koreanrevised"
        or runtime.get("pluginVersion") != PLUGIN_VERSION
        or runtime.get("assemblyCSharpSha256") != _ASSEMBLY_SHA256
        or runtime.get("recommendedPeglinPack") != "BepInExPack_Peglin 5.4.2100"
        or runtime.get("minimumBepInExVersion") != "5.4.21"
    ):
        raise ValueError("Plugin integrity manifest has unsupported runtime metadata.")


def _manager_readme(input_sha256: str, contents: dict[str, bytes]) -> bytes:
    return (
        "# Peglin Korean Revised — experimental local manager candidate\n\n"
        "이 패키지는 관리자 설치 동작 검증을 위한 로컬 후보입니다. 공개 배포본이나 "
        "관리자 설치 검증 완료본이 아닙니다. 번역은 DRAFT이며 일부 문구와 실제 플레이 "
        "상황을 확인하지 못했습니다. 개발 과정에서 AI 도구의 도움을 받았습니다.\n\n"
        "## 지원 대상과 무결성\n\n"
        "Steam 빌드 22988052, Unity 2022.3.62f2의 Windows Peglin만 대상으로 합니다. "
        "플러그인은 게임 파일 해시가 일치할 때만 번역을 적용합니다.\n\n"
        f"- resources.assets SHA-256: `{_SOURCE['assetSha256']}`\n"
        f"- Assembly-CSharp.dll SHA-256: `{_ASSEMBLY_SHA256}`\n"
        f"- 패키징 입력 ZIP SHA-256: `{input_sha256}`\n"
        f"- 플러그인 DLL SHA-256: `{_digest(contents[_DLL])}`\n"
        f"- 번역 오버레이 SHA-256: `{_digest(contents[_OVERLAY])}`\n\n"
        "## 프로필 사용 안내\n\n"
        "Peglin을 종료하고 별도의 시험용 프로필에서 이 ZIP을 로컬 패키지로 가져와 "
        "설치하세요. 패키지의 유일한 의존성은 Peglin용 BepInEx 팩입니다. "
        "이 후보에는 `BepInEx.cfg`가 없으며 기존 설정을 덮어쓰지 않습니다. "
        "자격 확인에 사용한 환경은 프로필의 `BepInEx/config/BepInEx.cfg`에서 "
        "`[Preloader.Entrypoint] Type = MonoBehaviour`였습니다. 관리자 기본 팩의 "
        "설정 및 실행 동작은 별도로 확인해야 합니다.\n\n"
        "업데이트를 시험할 때는 동일한 시험용 프로필에서 이전 로컬 패키지의 활성 "
        "상태와 파일을 확인한 뒤 새 ZIP을 가져오세요. 비활성화는 프로필에서 이 "
        "패키지의 활성 상태를 변경하고, 제거는 해당 프로필에서 이 패키지를 삭제하세요. "
        "각 단계 뒤 프로필의 플러그인 파일과 로그를 확인하세요. 관리자 화면의 "
        "구체적인 조작과 이 동작의 성공 여부는 아직 검증되지 않았습니다.\n\n"
        "문제가 생기면 사용한 프로필의 `BepInEx/LogOutput.log`에서 "
        "`Peglin Korean Revised` 메시지를 확인하세요. 전체 로그나 게임 파일은 "
        "공개하지 마세요. 자세한 수동 설치 및 상태 안내는 프로젝트 README를 참고하세요.\n\n"
        "## 라이선스\n\n"
        "코드에는 MIT 라이선스가 적용됩니다. 번역 자료는 MIT 범위에 포함되지 "
        "않습니다. 함께 제공된 LICENSE와 TRANSLATION-NOTICE.txt를 확인하세요.\n"
    ).encode("utf-8")


def create_manager_package(input_zip: Path, expected_sha256: str, output_zip: Path) -> Path:
    """Write a deterministic local package only after validating the complete input."""

    input_zip = input_zip.expanduser().resolve()
    output_zip = output_zip.expanduser().resolve()
    if input_zip == output_zip:
        raise ValueError("Manager package output must differ from its input ZIP.")
    contents = _read_qualified_input(input_zip, expected_sha256)
    _validate_candidate(contents)
    root_manifest = {
        "name": "PeglinKoreanRevised",
        "version_number": PACKAGE_VERSION,
        "website_url": "https://github.com/PiesP/peglin-korean-revised",
        "description": "Draft Korean localization for supported Peglin build 22988052.",
        "dependencies": ["BepInEx-BepInExPack_Peglin-5.4.2100"],
    }
    icon = files("peglin_l10n").joinpath("assets/icon.png").read_bytes()
    package = {
        _DLL: contents[_DLL],
        _OVERLAY: contents[_OVERLAY],
        _INTEGRITY: contents[_INTEGRITY],
        "LICENSE": contents["LICENSE"],
        "TRANSLATION-NOTICE.txt": contents["TRANSLATION-NOTICE.txt"],
        "README.md": _manager_readme(expected_sha256, contents),
        "manifest.json": (json.dumps(root_manifest, ensure_ascii=False, indent=2) + "\n").encode(),
        "icon.png": icon,
    }
    _write_zip_atomically(output_zip, package)
    return output_zip
