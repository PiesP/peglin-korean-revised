from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SOURCE_ROOT))

from peglin_l10n.release_tag import is_release_tag  # noqa: E402


ADMIN_LOGIN = "piesp"
GITHUB_ACTIONS_APP_ID = 15368
REQUIRED_CHECK_NAME = "validate"
RIGHTS_CONFIRMATION = "번역 기여 이용 허락에 동의하며 제출 권한이 있음을 확인합니다."


def github_api(repository: str, endpoint: str, *, paginate: bool = False) -> Any:
    command = ["gh", "api"]
    if paginate:
        command.extend(("--paginate", "--slurp"))
    command.append(f"repos/{repository}/{endpoint}")
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def has_rights_confirmation(body: object) -> bool:
    return isinstance(body, str) and re.search(
        rf"(?im)^\s*-\s*\[x\]\s*{re.escape(RIGHTS_CONFIRMATION)}\s*$", body
    ) is not None


def has_successful_required_check(repository: str, head_sha: str) -> bool:
    response = github_api(
        repository,
        f"commits/{head_sha}/check-runs?check_name={REQUIRED_CHECK_NAME}"
        "&filter=latest&per_page=100",
    )
    if (
        not isinstance(response, dict)
        or type(response.get("total_count")) is not int
        or response["total_count"] < 0
        or not isinstance(response.get("check_runs"), list)
    ):
        raise SystemExit("GitHub returned an invalid check runs response.")

    check_runs = response["check_runs"]
    for check_run in check_runs:
        if (
            not isinstance(check_run, dict)
            or not isinstance(check_run.get("name"), str)
            or not isinstance(check_run.get("head_sha"), str)
            or not isinstance(check_run.get("status"), str)
            or (
                check_run.get("conclusion") is not None
                and not isinstance(check_run.get("conclusion"), str)
            )
            or not isinstance(check_run.get("app"), dict)
            or type(check_run["app"].get("id")) is not int
        ):
            raise SystemExit("GitHub returned an invalid check run.")

    if response["total_count"] != len(check_runs) or len(check_runs) != 1:
        return False

    check_run = check_runs[0]
    return (
        check_run["name"] == REQUIRED_CHECK_NAME
        and check_run["head_sha"] == head_sha
        and check_run["status"] == "completed"
        and check_run["conclusion"] == "success"
        and check_run["app"]["id"] == GITHUB_ACTIONS_APP_ID
    )


def load_associated_pull_requests(
    repository: str, associated_pull_requests: list[object]
) -> list[dict[str, Any]]:
    pull_requests: list[dict[str, Any]] = []
    seen_numbers: set[int] = set()
    for association in associated_pull_requests:
        if (
            not isinstance(association, dict)
            or type(association.get("number")) is not int
            or association["number"] <= 0
        ):
            raise SystemExit("GitHub returned an invalid associated pull request.")
        number = association["number"]
        if number in seen_numbers:
            continue
        seen_numbers.add(number)
        pull_request = github_api(repository, f"pulls/{number}")
        if (
            not isinstance(pull_request, dict)
            or pull_request.get("number") != number
            or not isinstance(pull_request.get("base"), dict)
            or not isinstance(pull_request["base"].get("ref"), str)
        ):
            raise SystemExit(f"GitHub returned invalid details for PR #{number}.")
        pull_requests.append(pull_request)
    return pull_requests


def verified_pull_requests(
    repository: str, source_sha: str, pull_requests: list[dict[str, Any]]
) -> list[tuple[dict[str, Any], str]]:
    merged_pull_requests = [
        pull_request
        for pull_request in pull_requests
        if pull_request.get("merged_at")
        and isinstance(pull_request.get("base"), dict)
        and pull_request["base"].get("ref") == "master"
        and pull_request.get("merge_commit_sha") == source_sha
    ]
    verified: list[tuple[dict[str, Any], str]] = []
    for pull_request in merged_pull_requests:
        merged_by = pull_request.get("merged_by")
        author = pull_request.get("user")
        head = pull_request.get("head")
        number = pull_request.get("number")
        if (
            type(number) is not int
            or number <= 0
            or not isinstance(merged_by, dict)
            or str(merged_by.get("login", "")).casefold() != ADMIN_LOGIN
            or not isinstance(author, dict)
            or not isinstance(author.get("login"), str)
            or not isinstance(head, dict)
            or not isinstance(head.get("sha"), str)
            or re.fullmatch(r"[0-9a-f]{40}", head["sha"]) is None
            or not has_rights_confirmation(pull_request.get("body"))
        ):
            continue

        if not has_successful_required_check(repository, head["sha"]):
            continue

        if author["login"].casefold() == ADMIN_LOGIN:
            verified.append(
                (pull_request, "administrator-authored and manually merged")
            )
            continue

        review_pages = github_api(
            repository, f"pulls/{number}/reviews", paginate=True
        )
        if not isinstance(review_pages, list) or any(
            not isinstance(page, list) for page in review_pages
        ):
            raise SystemExit(f"GitHub returned invalid reviews for PR #{number}.")
        reviews = [review for page in review_pages for review in page]
        administrator_reviews = [
            review
            for review in reviews
            if isinstance(review, dict)
            and isinstance(review.get("user"), dict)
            and str(review["user"].get("login", "")).casefold() == ADMIN_LOGIN
            and review.get("state")
            in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}
        ]
        latest_review = max(
            administrator_reviews,
            key=lambda review: (
                str(review.get("submitted_at") or ""),
                int(review.get("id") or 0),
            ),
            default=None,
        )
        if (
            latest_review is not None
            and latest_review.get("state") == "APPROVED"
            and latest_review.get("commit_id") == head["sha"]
        ):
            verified.append((pull_request, "approved by @PiesP and manually merged"))
    return verified


def issue_number_from_commit_message(message: object) -> int | None:
    if not isinstance(message, str):
        return None
    lines = [line.strip() for line in message.splitlines() if line.strip()]
    if not lines:
        return None
    match = re.fullmatch(r"Issue: #([1-9][0-9]*)", lines[-1])
    return int(match.group(1)) if match else None


def translation_csv_changed(commit: object) -> bool:
    files = commit.get("files") if isinstance(commit, dict) else None
    if not isinstance(files, list) or not files or len(files) >= 300:
        return False
    if any(
        not isinstance(item, dict)
        or not isinstance(item.get("filename"), str)
        or re.fullmatch(r"translation/terms/[^/]+\.csv", item["filename"]) is None
        for item in files
    ):
        return False
    return any(item.get("status") != "removed" for item in files)


def issue_has_permission(repository: str, issue_number: int) -> bool:
    issue = github_api(repository, f"issues/{issue_number}")
    return (
        isinstance(issue, dict)
        and "pull_request" not in issue
        and has_rights_confirmation(issue.get("body"))
    )


def resolve_annotated_release_tag(
    repository: str, release_tag: str, source_sha: str
) -> tuple[str, str] | None:
    tag_reference = github_api(repository, f"git/ref/tags/{release_tag}")
    if (
        not isinstance(tag_reference, dict)
        or tag_reference.get("ref") != f"refs/tags/{release_tag}"
        or not isinstance(tag_reference.get("object"), dict)
    ):
        return None
    reference_object = tag_reference["object"]
    tag_object_sha = reference_object.get("sha")
    if (
        reference_object.get("type") != "tag"
        or not isinstance(tag_object_sha, str)
        or re.fullmatch(r"[0-9a-f]{40}", tag_object_sha) is None
    ):
        return None

    tag_object = github_api(repository, f"git/tags/{tag_object_sha}")
    target = tag_object.get("object") if isinstance(tag_object, dict) else None
    if (
        not isinstance(tag_object, dict)
        or tag_object.get("tag") != release_tag
        or not isinstance(target, dict)
        or target.get("type") != "commit"
        or not isinstance(target.get("sha"), str)
        or re.fullmatch(r"[0-9a-f]{40}", target["sha"]) is None
        or target["sha"] != source_sha
    ):
        return None
    return tag_object_sha, target["sha"]


def source_is_current_master_tip(repository: str, source_sha: str) -> bool:
    reference = github_api(repository, "git/ref/heads/master")
    target = reference.get("object") if isinstance(reference, dict) else None
    return (
        isinstance(target, dict)
        and target.get("type") == "commit"
        and target.get("sha") == source_sha
    )


def write_result(
    eligible: bool,
    summary: str,
    *,
    source_sha: str = "",
    release_tag: str = "",
    tag_object_sha: str = "",
) -> None:
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
        output.write(f"eligible={'true' if eligible else 'false'}\n")
        output.write(f"source_sha={source_sha}\n")
        output.write(f"release_tag={release_tag}\n")
        output.write(f"tag_object_sha={tag_object_sha}\n")
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open(
        "a", encoding="utf-8"
    ) as report:
        report.write(summary + "\n")


def verify_release_source() -> None:
    source_sha = os.environ["SOURCE_SHA"]
    source_ref = os.environ["SOURCE_REF"]
    release_tag = os.environ["RELEASE_TAG"]
    if (
        os.environ["EVENT_NAME"] != "push"
        or source_ref != f"refs/tags/{release_tag}"
        or not is_release_tag(release_tag)
    ):
        write_result(False, "Release rejected: event ref is not a valid translation version tag.")
        return

    if os.environ["EVENT_ACTOR"].casefold() != ADMIN_LOGIN:
        write_result(False, "Release rejected: the version tag must be pushed by @PiesP.")
        return

    repository = os.environ["GITHUB_REPOSITORY"]
    resolved_tag = resolve_annotated_release_tag(repository, release_tag, source_sha)
    if resolved_tag is None:
        write_result(
            False,
            "Release rejected: the version tag must be an annotated tag that points "
            "directly to the event commit.",
            source_sha=source_sha,
            release_tag=release_tag,
        )
        return
    tag_object_sha, resolved_source_sha = resolved_tag
    if not source_is_current_master_tip(repository, resolved_source_sha):
        write_result(
            False,
            "Release rejected: the version tag must target the current master tip.",
            source_sha=resolved_source_sha,
            release_tag=release_tag,
            tag_object_sha=tag_object_sha,
        )
        return

    associated_pull_requests = github_api(
        repository, f"commits/{resolved_source_sha}/pulls"
    )
    if not isinstance(associated_pull_requests, list):
        raise SystemExit("GitHub returned an invalid pull request list.")
    pull_requests = load_associated_pull_requests(
        repository, associated_pull_requests
    )

    verified_prs = verified_pull_requests(
        repository, resolved_source_sha, pull_requests
    )
    if verified_prs:
        if not has_successful_required_check(repository, resolved_source_sha):
            write_result(
                False,
                "Release rejected: wait for a successful `validate` check on the exact "
                "merged master commit, then create a new version tag.",
                source_sha=resolved_source_sha,
                release_tag=release_tag,
                tag_object_sha=tag_object_sha,
            )
            return
        descriptions = ", ".join(
            f"PR #{pull_request['number']} ({method})"
            for pull_request, method in verified_prs
        )
        write_result(
            True,
            "Release source verified as permission-confirmed "
            f"{descriptions} with a successful required validate check.",
            source_sha=resolved_source_sha,
            release_tag=release_tag,
            tag_object_sha=tag_object_sha,
        )
        return

    has_associated_master_pr = any(
        isinstance(pull_request, dict)
        and isinstance(pull_request.get("base"), dict)
        and pull_request["base"].get("ref") == "master"
        for pull_request in pull_requests
    )
    if not has_associated_master_pr:
        source_commit = github_api(repository, f"commits/{resolved_source_sha}")
        commit_details = (
            source_commit.get("commit")
            if isinstance(source_commit, dict)
            else None
        )
        parents = (
            source_commit.get("parents")
            if isinstance(source_commit, dict)
            else None
        )
        if (
            not isinstance(source_commit, dict)
            or source_commit.get("sha") != resolved_source_sha
            or not isinstance(commit_details, dict)
            or not isinstance(commit_details.get("message"), str)
            or not isinstance(parents, list)
            or len(parents) != 1
            or not isinstance(parents[0], dict)
            or not isinstance(parents[0].get("sha"), str)
            or re.fullmatch(r"[0-9a-f]{40}", parents[0]["sha"]) is None
        ):
            write_result(
                False,
                "Release rejected: an administrator issue update must be a single-parent commit.",
                source_sha=resolved_source_sha,
                release_tag=release_tag,
                tag_object_sha=tag_object_sha,
            )
            return
        issue_number = issue_number_from_commit_message(commit_details["message"])
        if issue_number is None:
            write_result(
                False,
                "Release rejected: add an `Issue: #<number>` trailer to the final line "
                "of the administrator issue commit message.",
                source_sha=resolved_source_sha,
                release_tag=release_tag,
                tag_object_sha=tag_object_sha,
            )
            return
        if not translation_csv_changed(source_commit):
            write_result(
                False,
                "Release rejected: an administrator issue commit must change translation "
                "CSV files only.",
                source_sha=resolved_source_sha,
                release_tag=release_tag,
                tag_object_sha=tag_object_sha,
            )
            return
        if not issue_has_permission(repository, issue_number):
            write_result(
                False,
                f"Release rejected: issue #{issue_number} does not contain the checked "
                "translation permission confirmation.",
                source_sha=resolved_source_sha,
                release_tag=release_tag,
                tag_object_sha=tag_object_sha,
            )
            return
        if not has_successful_required_check(repository, resolved_source_sha):
            write_result(
                False,
                "Release rejected: wait for a successful `validate` check on the issue "
                "commit, then rerun this workflow while that commit remains the master tip.",
                source_sha=resolved_source_sha,
                release_tag=release_tag,
                tag_object_sha=tag_object_sha,
            )
            return
        write_result(
            True,
            "Release source verified as a single-commit administrator translation from "
            f"permission-confirmed issue #{issue_number}.",
            source_sha=resolved_source_sha,
            release_tag=release_tag,
            tag_object_sha=tag_object_sha,
        )
        return

    write_result(
        False,
        "Release rejected: the source must be a rights-confirmed PR merged by @PiesP "
        "with a successful `validate` check, or a single-parent CSV-only issue commit "
        "with a rights-confirmed issue and successful `validate` check.",
        source_sha=resolved_source_sha,
        release_tag=release_tag,
        tag_object_sha=tag_object_sha,
    )


if __name__ == "__main__":
    verify_release_source()
