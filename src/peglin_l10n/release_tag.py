"""Policy for administrator-selected translation release tags."""

from __future__ import annotations

import re


RELEASE_TAG_PATTERN = re.compile(
    r"peglin-ko-v(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)"
    r"(?:-rc\.[1-9][0-9]*)?"
)


def is_release_tag(value: str) -> bool:
    return RELEASE_TAG_PATTERN.fullmatch(value) is not None


def is_prerelease_tag(value: str) -> bool:
    return value.startswith("peglin-ko-v") and "-rc." in value


def validate_release_tag_status(release_tag: str, status: str) -> bool:
    """Validate version syntax and require draft tags to be RCs."""

    if not is_release_tag(release_tag):
        raise ValueError("Release tag must use peglin-ko-vX.Y.Z or peglin-ko-vX.Y.Z-rc.N.")
    if status not in {"draft", "approved"}:
        raise ValueError("Translation status must be draft or approved.")
    prerelease = is_prerelease_tag(release_tag)
    if prerelease != (status == "draft"):
        raise ValueError(
            "Draft translations require an -rc.N tag; approved translations require a stable version tag."
        )
    return prerelease
