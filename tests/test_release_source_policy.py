from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "scripts"
    / "verify_release_source.py"
)
SPEC = importlib.util.spec_from_file_location("verify_release_source", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Could not load release source verification script.")
release_source = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_source)


class ReleaseSourcePolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source_sha = "a" * 40
        self.issue_number = 42
        self.rights_confirmation = (
            "- [x] " + release_source.RIGHTS_CONFIRMATION
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _issue_event(self, *, commits: list[dict[str, str]] | None = None) -> dict:
        return {
            "before": "b" * 40,
            "after": self.source_sha,
            "commits": commits
            if commits is not None
            else [{"id": self.source_sha}],
            "head_commit": {
                "id": self.source_sha,
                "message": f"Update Korean translation\n\nIssue: #{self.issue_number}",
            },
        }

    def _run(
        self,
        *,
        event_name: str = "push",
        actor: str = "PiesP",
        triggering_actor: str = "PiesP",
        event: dict | None = None,
        responses: dict[object, object] | None = None,
    ) -> bool:
        event_path = self.root / "event.json"
        event_path.write_text(
            json.dumps(event if event is not None else self._issue_event()),
            encoding="utf-8",
        )
        output_path = self.root / "output.txt"
        summary_path = self.root / "summary.md"
        response_map = dict(responses or {})
        response_map.setdefault(f"commits/{self.source_sha}/pulls", [])

        def api_response(
            repository: str, endpoint: str, *, paginate: bool = False
        ) -> object:
            return response_map.get(
                (endpoint, paginate), response_map.get(endpoint)
            )

        environment = {
            "SOURCE_SHA": self.source_sha,
            "SOURCE_REF": "refs/heads/master",
            "EVENT_NAME": event_name,
            "EVENT_ACTOR": actor,
            "TRIGGERING_ACTOR": triggering_actor,
            "EVENT_PATH": str(event_path),
            "GITHUB_REPOSITORY": "PiesP/peglin-korean-revised",
            "GITHUB_OUTPUT": str(output_path),
            "GITHUB_STEP_SUMMARY": str(summary_path),
        }
        with patch.dict(os.environ, environment), patch.object(
            release_source, "github_api", side_effect=api_response
        ):
            release_source.verify_release_source()
        return "eligible=true" in output_path.read_text(encoding="utf-8")

    def _valid_issue_responses(self) -> dict[object, object]:
        return {
            f"commits/{self.source_sha}/pulls": [],
            f"commits/{self.source_sha}": {
                "files": [
                    {
                        "filename": "translation/terms/menu.csv",
                        "status": "modified",
                    }
                ]
            },
            f"issues/{self.issue_number}": {
                "body": self.rights_confirmation
            },
        }

    def _pull_request(
        self,
        *,
        author: str = "PiesP",
        merged_by: str = "PiesP",
        body: str | None = None,
    ) -> dict[str, object]:
        return {
            "number": 7,
            "merged_at": "2026-09-24T00:00:00Z",
            "merge_commit_sha": self.source_sha,
            "merged_by": {"login": merged_by},
            "user": {"login": author},
            "base": {"ref": "master"},
            "head": {"sha": "c" * 40},
            "body": self.rights_confirmation if body is None else body,
        }

    def _successful_validate_check(self, *, head_sha: str = "c" * 40) -> dict:
        return {
            "total_count": 1,
            "check_runs": [
                {
                    "name": "validate",
                    "head_sha": head_sha,
                    "status": "completed",
                    "conclusion": "success",
                    "app": {"id": 15368},
                }
            ],
        }

    def _valid_pr_responses(
        self, pull_request: dict[str, object]
    ) -> dict[object, object]:
        head = pull_request["head"]
        assert isinstance(head, dict)
        head_sha = head["sha"]
        assert isinstance(head_sha, str)
        check_runs_endpoint = (
            f"commits/{head_sha}/check-runs?check_name=validate"
            "&filter=latest&per_page=100"
        )
        return {
            f"commits/{self.source_sha}/pulls": [{"number": 7}],
            "pulls/7": pull_request,
            check_runs_endpoint: self._successful_validate_check(head_sha=head_sha),
            ("pulls/7/reviews", True): [[]],
        }

    def test_accepts_single_admin_commit_for_permission_confirmed_issue(self) -> None:
        self.assertTrue(self._run(responses=self._valid_issue_responses()))

    def test_rejects_issue_push_with_multiple_commits(self) -> None:
        commits = [
            {"id": "c" * 40},
            {"id": self.source_sha},
        ]
        self.assertFalse(
            self._run(event=self._issue_event(commits=commits))
        )

    def test_rejects_issue_commit_that_also_changes_non_translation_files(self) -> None:
        responses = self._valid_issue_responses()
        responses[f"commits/{self.source_sha}"] = {
            "files": [
                {
                    "filename": "translation/terms/menu.csv",
                    "status": "modified",
                },
                {"filename": "plugin/Plugin.cs", "status": "modified"},
            ]
        }
        self.assertFalse(self._run(responses=responses))

    def test_rejects_issue_without_permission_confirmation(self) -> None:
        responses = self._valid_issue_responses()
        responses[f"issues/{self.issue_number}"] = {
            "body": "- [ ] " + release_source.RIGHTS_CONFIRMATION
        }
        self.assertFalse(self._run(responses=responses))

    def test_rejects_admin_direct_push_when_commit_is_associated_with_a_pr(self) -> None:
        responses = self._valid_issue_responses()
        responses[f"commits/{self.source_sha}/pulls"] = [
            {"number": 7}
        ]
        responses["pulls/7"] = self._pull_request(body="")
        self.assertFalse(self._run(responses=responses))

    def test_accepts_admin_pr_when_association_omits_merge_details(self) -> None:
        pull_request = self._pull_request()
        self.assertTrue(
            self._run(responses=self._valid_pr_responses(pull_request))
        )

    def test_accepts_other_authored_pr_with_current_admin_approval(self) -> None:
        pull_request = self._pull_request(author="translator")
        responses = self._valid_pr_responses(pull_request)
        responses[("pulls/7/reviews", True)] = [
            [
                {
                    "id": 1,
                    "user": {"login": "PiesP"},
                    "state": "APPROVED",
                    "commit_id": "c" * 40,
                    "submitted_at": "2026-09-24T00:00:00Z",
                }
            ]
        ]
        self.assertTrue(self._run(responses=responses))

    def test_rejects_admin_pr_with_wrong_author_or_merger(self) -> None:
        for pull_request in (
            self._pull_request(author="translator"),
            self._pull_request(merged_by="maintainer"),
        ):
            with self.subTest(pull_request=pull_request):
                self.assertFalse(
                    self._run(responses=self._valid_pr_responses(pull_request))
                )

    def test_rejects_admin_pr_without_permission_confirmation(self) -> None:
        pull_request = self._pull_request(
            body="- [ ] " + release_source.RIGHTS_CONFIRMATION
        )
        self.assertFalse(
            self._run(responses=self._valid_pr_responses(pull_request))
        )

    def test_rejects_pr_whose_merge_commit_is_not_the_source(self) -> None:
        pull_request = self._pull_request()
        pull_request["merge_commit_sha"] = "d" * 40
        self.assertFalse(
            self._run(responses=self._valid_pr_responses(pull_request))
        )

    def test_rejects_pr_without_successful_required_validate_check(self) -> None:
        check_responses = (
            {"total_count": 0, "check_runs": []},
            {
                "total_count": 1,
                "check_runs": [
                    {
                        "name": "validate",
                        "head_sha": "c" * 40,
                        "status": "completed",
                        "conclusion": "failure",
                        "app": {"id": 15368},
                    }
                ],
            },
            self._successful_validate_check(head_sha="d" * 40),
            {
                "total_count": 1,
                "check_runs": [
                    {
                        "name": "validate",
                        "head_sha": "c" * 40,
                        "status": "completed",
                        "conclusion": "success",
                        "app": {"id": 1},
                    }
                ],
            },
        )
        endpoint = (
            f"commits/{'c' * 40}/check-runs?check_name=validate"
            "&filter=latest&per_page=100"
        )
        for check_response in check_responses:
            responses = self._valid_pr_responses(self._pull_request())
            responses[endpoint] = check_response
            with self.subTest(check_response=check_response):
                self.assertFalse(self._run(responses=responses))

    def test_rejects_malformed_check_run_response(self) -> None:
        responses = self._valid_pr_responses(self._pull_request())
        endpoint = (
            f"commits/{'c' * 40}/check-runs?check_name=validate"
            "&filter=latest&per_page=100"
        )
        responses[endpoint] = {"total_count": 1, "check_runs": [None]}
        with self.assertRaises(SystemExit):
            self._run(responses=responses)

    def test_rejects_duplicate_or_incomplete_required_check_response(self) -> None:
        endpoint = (
            f"commits/{'c' * 40}/check-runs?check_name=validate"
            "&filter=latest&per_page=100"
        )
        one_check = self._successful_validate_check()["check_runs"][0]
        for check_response in (
            {"total_count": 2, "check_runs": [one_check, dict(one_check)]},
            {"total_count": 2, "check_runs": [one_check]},
        ):
            responses = self._valid_pr_responses(self._pull_request())
            responses[endpoint] = check_response
            with self.subTest(check_response=check_response):
                self.assertFalse(self._run(responses=responses))

    def test_rejects_other_authored_pr_without_current_admin_approval(self) -> None:
        pull_request = self._pull_request(author="translator")
        review_pages = (
            [[]],
            [
                [
                    {
                        "id": 1,
                        "user": {"login": "PiesP"},
                        "state": "APPROVED",
                        "commit_id": "d" * 40,
                        "submitted_at": "2026-09-24T00:00:00Z",
                    }
                ]
            ],
            [
                [
                    {
                        "id": 1,
                        "user": {"login": "PiesP"},
                        "state": "APPROVED",
                        "commit_id": "c" * 40,
                        "submitted_at": "2026-09-24T00:00:00Z",
                    },
                    {
                        "id": 2,
                        "user": {"login": "PiesP"},
                        "state": "CHANGES_REQUESTED",
                        "commit_id": "c" * 40,
                        "submitted_at": "2026-09-24T01:00:00Z",
                    },
                ]
            ],
        )
        for reviews in review_pages:
            responses = self._valid_pr_responses(pull_request)
            responses[("pulls/7/reviews", True)] = reviews
            with self.subTest(reviews=reviews):
                self.assertFalse(self._run(responses=responses))


if __name__ == "__main__":
    unittest.main()
