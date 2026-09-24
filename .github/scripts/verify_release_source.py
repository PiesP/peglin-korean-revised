from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any


ADMIN_LOGIN = "piesp"
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


def verified_pull_requests(
    repository: str, source_sha: str, associated_pull_requests: list[object]
) -> list[dict[str, Any]]:
    merged_pull_requests = [
        pull_request
        for pull_request in associated_pull_requests
        if isinstance(pull_request, dict)
        and pull_request.get("merged_at")
        and isinstance(pull_request.get("base"), dict)
        and pull_request["base"].get("ref") == "master"
        and pull_request.get("merge_commit_sha") == source_sha
    ]
    verified: list[dict[str, Any]] = []
    for pull_request in merged_pull_requests:
        merged_by = pull_request.get("merged_by")
        head = pull_request.get("head")
        number = pull_request.get("number")
        if (
            type(number) is not int
            or number <= 0
            or not isinstance(merged_by, dict)
            or str(merged_by.get("login", "")).casefold() != ADMIN_LOGIN
            or not isinstance(head, dict)
            or not isinstance(head.get("sha"), str)
            or not has_rights_confirmation(pull_request.get("body"))
        ):
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
            verified.append(pull_request)
    return verified


def issue_number_from_commit_message(message: object) -> int | None:
    if not isinstance(message, str):
        return None
    lines = [line.strip() for line in message.splitlines() if line.strip()]
    if not lines:
        return None
    match = re.fullmatch(r"Issue: #([1-9][0-9]*)", lines[-1])
    return int(match.group(1)) if match else None


def translation_csv_changed(repository: str, source_sha: str) -> bool:
    commit = github_api(repository, f"commits/{source_sha}")
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


def write_result(eligible: bool, summary: str) -> None:
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
        output.write(f"eligible={'true' if eligible else 'false'}\n")
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open(
        "a", encoding="utf-8"
    ) as report:
        report.write(summary + "\n")


def verify_release_source() -> None:
    source_sha = os.environ["SOURCE_SHA"]
    if os.environ["SOURCE_REF"] != "refs/heads/master":
        write_result(False, "Release skipped: source is not master.")
        return

    event_path = Path(os.environ["EVENT_PATH"])
    event = json.loads(event_path.read_text(encoding="utf-8"))
    repository = os.environ["GITHUB_REPOSITORY"]
    associated_pull_requests = github_api(
        repository, f"commits/{source_sha}/pulls"
    )
    if not isinstance(associated_pull_requests, list):
        raise SystemExit("GitHub returned an invalid pull request list.")

    approved_pull_requests = verified_pull_requests(
        repository, source_sha, associated_pull_requests
    )
    if approved_pull_requests:
        numbers = ", ".join(
            str(item["number"]) for item in approved_pull_requests
        )
        write_result(
            True,
            "Release source verified as a permission-confirmed PR "
            f"#{numbers}, approved by @PiesP and manually merged by @PiesP.",
        )
        return

    has_associated_master_pr = any(
        isinstance(pull_request, dict)
        and isinstance(pull_request.get("base"), dict)
        and pull_request["base"].get("ref") == "master"
        for pull_request in associated_pull_requests
    )
    actor = os.environ["EVENT_ACTOR"].casefold()
    triggering_actor = os.environ["TRIGGERING_ACTOR"].casefold()
    if (
        os.environ["EVENT_NAME"] == "push"
        and actor == ADMIN_LOGIN
        and triggering_actor == ADMIN_LOGIN
        and not has_associated_master_pr
    ):
        head_commit = event.get("head_commit")
        pushed_commits = event.get("commits")
        if (
            not isinstance(head_commit, dict)
            or head_commit.get("id") != source_sha
            or event.get("after") != source_sha
            or not isinstance(pushed_commits, list)
            or len(pushed_commits) != 1
            or not isinstance(pushed_commits[0], dict)
            or pushed_commits[0].get("id") != source_sha
        ):
            write_result(
                False,
                "Release skipped: issue updates must be a single-commit push to master.",
            )
            return
        issue_number = issue_number_from_commit_message(head_commit.get("message"))
        if issue_number is None:
            write_result(
                False,
                "Release skipped: an administrator issue update must end its commit "
                "message with the Issue: #<number> trailer.",
            )
            return
        if not translation_csv_changed(repository, source_sha):
            write_result(
                False,
                "Release skipped: the single issue commit must change translation CSV "
                "files only.",
            )
            return
        if not issue_has_permission(repository, issue_number):
            write_result(
                False,
                f"Release skipped: issue #{issue_number} lacks the required "
                "translation permission confirmation.",
            )
            return
        write_result(
            True,
            "Release source verified as administrator-applied translation from "
            f"permission-confirmed issue #{issue_number}.",
        )
        return

    write_result(
        False,
        "Release skipped: this commit lacks a current @PiesP approval and manual "
        "merge on a permission-confirmed PR, or a valid administrator-applied "
        "issue update.",
    )


if __name__ == "__main__":
    verify_release_source()
