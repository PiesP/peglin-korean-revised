"""Public source metadata and runtime provenance for hosted release builds."""

from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ElementTree
from collections.abc import Iterable
from pathlib import Path
from typing import Any


SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
PLUGIN_ATTRIBUTE_PATTERN = re.compile(
    r"\[\s*BepInPlugin\s*\(\s*[^,]+,\s*[^,]+,\s*\"([^\"]+)\"\s*\)\s*\]"
)
SOURCE_LOCK_FIELDS = {
    "schemaVersion",
    "kind",
    "game",
    "steamAppId",
    "language",
    "steamBuildId",
    "unityVersion",
    "resourcesAssetsSha256",
    "assemblyCSharpSha256",
    "sourceRowCount",
    "translationCount",
    "runtime",
    "terms",
}
DEFAULT_PLUGIN_SOURCE_INPUTS = (
    "plugin/NuGet.Config",
    "plugin/PeglinKoreanRevised.csproj",
    "plugin/Plugin.cs",
    "plugin/packages.lock.json",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def plugin_source_inputs_sha256(
    project_root: Path,
    relative_paths: Iterable[str] = DEFAULT_PLUGIN_SOURCE_INPUTS,
) -> str:
    """Hash plugin inputs with their repository paths in a stable order."""

    digest = hashlib.sha256()
    normalized = sorted(str(Path(path).as_posix()) for path in relative_paths)
    if not normalized:
        raise ValueError("At least one plugin source input is required.")
    for relative_path in normalized:
        if Path(relative_path).is_absolute() or ".." in Path(relative_path).parts:
            raise ValueError(f"Plugin source input must be repository-relative: {relative_path}")
        source_path = project_root / relative_path
        if not source_path.is_file():
            raise ValueError(f"Plugin source input was not found: {source_path}")
        contents = source_path.read_bytes()
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(len(contents).to_bytes(8, byteorder="big"))
        digest.update(contents)
    return digest.hexdigest()


def category_slug(category: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", category.casefold()).strip("-")
    if not slug:
        raise ValueError(f"Translation category cannot form a CSV slug: {category!r}.")
    return slug


def plugin_source_version(project_root: Path) -> str:
    """Read and cross-check the version declared by both plugin source files."""

    project_path = project_root / "plugin" / "PeglinKoreanRevised.csproj"
    plugin_path = project_root / "plugin" / "Plugin.cs"
    try:
        project = ElementTree.parse(project_path)
    except (OSError, ElementTree.ParseError) as exc:
        raise ValueError(f"Could not read plugin project version: {exc}") from exc
    project_versions = [
        element.text.strip()
        for element in project.getroot().iter()
        if element.tag.rsplit("}", 1)[-1] == "Version"
        and isinstance(element.text, str)
        and element.text.strip()
    ]
    if len(project_versions) != 1:
        raise ValueError("Plugin project must declare exactly one Version.")
    try:
        plugin_source = plugin_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Could not read Plugin.cs version: {exc}") from exc
    attribute_versions = PLUGIN_ATTRIBUTE_PATTERN.findall(plugin_source)
    if len(attribute_versions) != 1:
        raise ValueError("Plugin.cs must declare exactly one BepInPlugin version.")
    if project_versions[0] != attribute_versions[0]:
        raise ValueError(
            "Plugin.cs BepInPlugin version does not match the project Version."
        )
    return project_versions[0]


def read_source_lock(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read source lock: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Source lock root must be a JSON object.")
    if set(data) != SOURCE_LOCK_FIELDS:
        missing = sorted(SOURCE_LOCK_FIELDS - set(data))
        unexpected = sorted(set(data) - SOURCE_LOCK_FIELDS)
        raise ValueError(
            "Source lock root fields are invalid: "
            f"missing={missing!r}, unexpected={unexpected!r}."
        )
    expected = {
        "schemaVersion": 1,
        "kind": "peglin-korean-source-lock",
        "game": "Peglin",
        "steamAppId": "1296610",
        "language": "ko",
    }
    for field, value in expected.items():
        if data.get(field) != value:
            raise ValueError(f"Source lock {field} must be {value!r}.")
    for field in ("steamBuildId", "unityVersion"):
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Source lock {field} must be a nonempty string.")
    for field in ("resourcesAssetsSha256", "assemblyCSharpSha256"):
        value = data.get(field)
        if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
            raise ValueError(f"Source lock {field} must be a lowercase SHA-256 digest.")
    for field in ("sourceRowCount", "translationCount"):
        value = data.get(field)
        if type(value) is not int or value <= 0:
            raise ValueError(f"Source lock {field} must be a positive integer.")
    if data["sourceRowCount"] < data["translationCount"]:
        raise ValueError("Source lock sourceRowCount cannot be smaller than translationCount.")

    runtime = data.get("runtime")
    if not isinstance(runtime, dict):
        raise ValueError("Source lock runtime must be an object.")
    if set(runtime) != {"path", "pluginVersion", "sha256", "sourceInputsSha256"}:
        raise ValueError("Source lock runtime fields are invalid.")
    runtime_path = runtime.get("path")
    if (
        not isinstance(runtime_path, str)
        or Path(runtime_path).is_absolute()
        or ".." in Path(runtime_path).parts
    ):
        raise ValueError("Source lock runtime path must be repository-relative.")
    version = runtime.get("pluginVersion")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("Source lock runtime pluginVersion must be nonempty.")
    for field in ("sha256", "sourceInputsSha256"):
        value = runtime.get(field)
        if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
            raise ValueError(f"Source lock runtime {field} must be a lowercase SHA-256 digest.")

    terms = data.get("terms")
    if not isinstance(terms, dict) or not terms:
        raise ValueError("Source lock terms must be a nonempty object.")
    if len(terms) != data["translationCount"]:
        raise ValueError("Source lock translationCount does not match its term metadata.")
    for term, metadata in terms.items():
        if not isinstance(term, str) or not term.strip() or term != term.strip():
            raise ValueError("Source lock term keys must be nonempty and unpadded.")
        if not isinstance(metadata, dict) or set(metadata) != {
            "category",
            "file",
            "sourceFingerprint",
            "protectedTokens",
        }:
            raise ValueError(f"Source lock metadata fields are invalid for {term!r}.")
        category = metadata.get("category")
        file_name = metadata.get("file")
        fingerprint = metadata.get("sourceFingerprint")
        tokens = metadata.get("protectedTokens")
        if not isinstance(category, str) or not category.strip():
            raise ValueError(f"Source lock category is invalid for {term!r}.")
        term_category = term.split("/", 1)[0] if "/" in term else "General"
        if category != term_category:
            raise ValueError(
                f"Source lock category for {term!r} must match {term_category!r}."
            )
        if (
            not isinstance(file_name, str)
            or Path(file_name).name != file_name
            or not file_name.endswith(".csv")
        ):
            raise ValueError(f"Source lock file is invalid for {term!r}.")
        expected_file = f"{category_slug(category)}.csv"
        if file_name != expected_file:
            raise ValueError(
                f"Source lock CSV file for {term!r} must be {expected_file!r}."
            )
        if (
            not isinstance(fingerprint, str)
            or SHA256_PATTERN.fullmatch(fingerprint) is None
        ):
            raise ValueError(f"Source lock fingerprint is invalid for {term!r}.")
        if not isinstance(tokens, list) or any(
            not isinstance(token, str) for token in tokens
        ):
            raise ValueError(f"Source lock protectedTokens are invalid for {term!r}.")
    return data


def validate_runtime_provenance(
    project_root: Path,
    source_lock: dict[str, Any],
    source_inputs: Iterable[str] = DEFAULT_PLUGIN_SOURCE_INPUTS,
    package_version: str | None = None,
) -> Path:
    runtime = source_lock["runtime"]
    declared_version = plugin_source_version(project_root)
    if runtime["pluginVersion"] != declared_version:
        raise ValueError(
            "Source lock runtime pluginVersion does not match plugin source declarations."
        )
    if package_version is not None and package_version != declared_version:
        raise ValueError(
            "Candidate package pluginVersion does not match plugin source declarations."
        )
    plugin_path = project_root / runtime["path"]
    if not plugin_path.is_file():
        raise ValueError(f"Tracked runtime plugin was not found: {plugin_path}")
    if sha256_file(plugin_path) != runtime["sha256"]:
        raise ValueError("Tracked runtime plugin hash does not match source-lock.json.")
    actual_inputs_hash = plugin_source_inputs_sha256(project_root, source_inputs)
    if actual_inputs_hash != runtime["sourceInputsSha256"]:
        raise ValueError("Plugin source inputs do not match source-lock.json.")
    return plugin_path
