"""Recheck the protected tag and pass verified assets to GitHub CLI."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path


SHA = re.compile(r"[0-9a-f]{40}\Z")
TAG = re.compile(
    r"peglin-ko-v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)(?:-rc\.[1-9][0-9]*)?\Z"
)
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
OVERLAY = re.compile(r"[A-Za-z0-9._-]+\.json\Z")

Run = Callable[..., subprocess.CompletedProcess[str]]


def release_argv(
    root: Path, repository: str, source_sha: str, tag: str,
    prerelease: bool, overlay_name: str,
) -> list[str]:
    """Construct one release command from verified workflow outputs."""
    if SHA.fullmatch(source_sha) is None or TAG.fullmatch(tag) is None:
        raise ValueError("The selected source or release tag is invalid.")
    if REPOSITORY.fullmatch(repository) is None or OVERLAY.fullmatch(overlay_name) is None:
        raise ValueError("The repository or overlay name is invalid.")
    if ("-rc." in tag) != prerelease:
        raise ValueError("The prerelease flag disagrees with the selected tag.")
    archives = list(root.glob("*.zip"))
    if len(archives) != 1 or not archives[0].is_file() or archives[0].is_symlink():
        raise ValueError("Expected exactly one verified install archive.")
    assets = [
        root / overlay_name, archives[0], root / "LICENSE",
        root / "TRANSLATION-NOTICE.txt", root / "release-notes.md",
        root / "release-manifest.json", root / "SHA256SUMS.txt",
    ]
    if any(not path.is_file() or path.is_symlink() for path in assets):
        raise ValueError("A verified release asset is missing or is a symlink.")
    argv = [
        "gh", "release", "create", tag, "--verify-tag", "--target", source_sha,
        "--title", f"Peglin Korean Revised {tag.removeprefix('peglin-ko-')}",
        "--notes-file", str(root / "release-notes.md"),
    ]
    if prerelease:
        argv.append("--prerelease")
    argv.extend(["--repo", repository, *(str(path) for path in assets)])
    return argv


def publish_release(
    root: Path, repository: str, source_sha: str, tag: str,
    tag_object_sha: str, prerelease: bool, overlay_name: str,
    *, run: Run = subprocess.run,
) -> None:
    """Recheck the annotated tag object immediately before release creation."""
    argv = release_argv(root, repository, source_sha, tag, prerelease, overlay_name)
    if SHA.fullmatch(tag_object_sha) is None:
        raise ValueError("The verified tag object SHA is invalid.")
    result = run(
        ["gh", "api", f"repos/{repository}/git/ref/tags/{tag}", "--jq", ".object.sha"],
        check=True, capture_output=True, text=True,
    )
    if result.stdout.strip() != tag_object_sha:
        raise ValueError("The protected release tag changed after source verification.")
    run(argv, check=True)


def main() -> int:
    try:
        prerelease = os.environ["PRERELEASE"]
        if prerelease not in {"true", "false"}:
            raise ValueError("The prerelease output is invalid.")
        publish_release(
            Path(os.environ["RELEASE_DIR"]), os.environ["GITHUB_REPOSITORY"],
            os.environ["SOURCE_SHA"], os.environ["RELEASE_TAG"],
            os.environ["TAG_OBJECT_SHA"], prerelease == "true",
            os.environ["OVERLAY_NAME"],
        )
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
