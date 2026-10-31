import copy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from merge_dependabot import APIError, GitHub, all_jobs_passed, eligible, ensure_main_ci, latest_run, process


class MergeTests(unittest.TestCase):
    def setUp(self):
        reporter = patch("merge_dependabot.report")
        reporter.start()
        self.addCleanup(reporter.stop)
        self.base, self.head = "a" * 40, "b" * 40
        self.pr = {
            "number": 25, "state": "open", "draft": False,
            "user": {"login": "dependabot[bot]"}, "base": {"ref": "main"},
            "head": {"sha": self.head, "repo": {"full_name": "owner/repo"}},
        }
        self.run = {
            "id": 123, "head_sha": self.head, "head_repository": {"full_name": "owner/repo"},
            "event": "pull_request", "pull_requests": [{"number": 25}],
            "status": "completed", "conclusion": "success", "run_attempt": 1,
        }
        self.gh = Mock(spec=GitHub)
        self.gh.repo, self.gh.default = "owner/repo", "main"
        self.gh.pr.return_value = copy.deepcopy(self.pr)
        self.gh.head.return_value = self.base
        self.gh.contains.return_value = True
        self.gh.runs.return_value = [copy.deepcopy(self.run)]
        self.gh.jobs.return_value = {"total_count": 2, "jobs": [
            {"status": "completed", "conclusion": "success"},
            {"status": "completed", "conclusion": "success"},
        ]}

    def test_success_merges_exact_head_and_checks_published_main(self):
        process(self.gh, 25)
        self.gh.merge.assert_called_once_with(25, self.head)
        self.gh.dispatch.assert_called_once_with("main")

    def test_humans_forks_drafts_and_other_targets_are_excluded(self):
        for change in (
            {"user": {"login": "human"}}, {"draft": True}, {"state": "closed"},
            {"base": {"ref": "release"}}, {"head": {"repo": {"full_name": "someone/fork"}}},
            {"head": {"repo": None}},
        ):
            with self.subTest(change=change):
                self.assertFalse(eligible({**self.pr, **change}, "owner/repo", "main"))
        self.assertTrue(eligible({**self.pr, "title": "Major action update to an unpinned tag"}, "owner/repo", "main"))

    def test_head_and_main_changes_block_merge(self):
        for changed in ("head", "base"):
            with self.subTest(changed=changed):
                gh = self.gh
                gh.reset_mock()
                current = copy.deepcopy(self.pr)
                if changed == "head":
                    current["head"]["sha"] = "c" * 40
                    gh.head.side_effect = None
                else:
                    gh.head.side_effect = [self.base, "c" * 40]
                gh.pr.side_effect = [copy.deepcopy(self.pr), current]
                process(gh, 25)
                gh.merge.assert_not_called()

    def test_incomplete_skipped_or_failed_jobs_block_merge(self):
        for jobs in (
            {"total_count": 0, "jobs": []},
            {"total_count": 2, "jobs": [{"status": "completed", "conclusion": "success"}]},
            {"total_count": 1, "jobs": [{"status": "completed", "conclusion": "skipped"}]},
            {"total_count": 1, "jobs": [{"status": "in_progress", "conclusion": None}]},
            {"total_count": 1, "jobs": [{"status": "completed", "conclusion": "failure"}]},
        ):
            with self.subTest(jobs=jobs):
                self.assertFalse(all_jobs_passed(jobs))
                self.gh.jobs.return_value = jobs
                process(self.gh, 25)
                self.gh.merge.assert_not_called()

    def test_pending_ci_is_never_merged_or_retried(self):
        self.gh.runs.return_value = [{**self.run, "status": "in_progress", "conclusion": None}]
        process(self.gh, 25)
        self.gh.merge.assert_not_called()
        self.gh.retry.assert_not_called()

    def test_failed_jobs_are_retried_only_once(self):
        self.gh.runs.return_value = [{**self.run, "conclusion": "failure"}]
        process(self.gh, 25)
        self.gh.retry.assert_called_once_with(123)
        self.gh.reset_mock()
        self.gh.runs.return_value = [{**self.run, "conclusion": "failure", "run_attempt": 2}]
        process(self.gh, 25)
        self.gh.retry.assert_not_called()
        self.gh.merge.assert_not_called()

    def test_approval_required_duplicate_does_not_block_explicit_ci(self):
        self.gh.runs.return_value = [{**self.run, "conclusion": "action_required"}]
        process(self.gh, 25)
        tag = f"automation/dependabot-ci/25/{self.base[:16]}-{self.head[:16]}"
        self.gh.create_ref.assert_called_once_with(tag, self.head)
        self.gh.dispatch.assert_called_once_with(tag, self.base)
        self.gh.merge.assert_not_called()

    def test_stale_branch_is_updated_before_validation(self):
        updated = copy.deepcopy(self.pr)
        updated["head"]["sha"] = "c" * 40
        self.gh.contains.side_effect = [False, True]
        self.gh.pr.side_effect = [self.pr, updated]
        self.gh.runs.return_value = []
        process(self.gh, 25)
        self.gh.refresh.assert_called_once_with(25, self.head)
        self.gh.create_ref.assert_called_once_with(
            f"automation/dependabot-ci/25/{self.base[:16]}-{'c' * 16}", "c" * 40,
        )
        self.gh.merge.assert_not_called()

    def test_unrelated_or_older_runs_are_not_reused(self):
        stale = {**self.run, "id": 124, "head_sha": "c" * 40}
        wrong_pr = {**self.run, "id": 125, "pull_requests": [{"number": 26}]}
        self.assertEqual(latest_run([stale, wrong_pr, self.run], self.pr, "tag", "owner/repo"), self.run)
        tag_run = {**self.run, "id": 126, "event": "workflow_dispatch", "head_branch": "tag"}
        self.assertEqual(latest_run([self.run, tag_run], self.pr, "tag", "owner/repo"), tag_run)

    def test_published_main_ci_is_started_only_when_missing(self):
        self.gh.runs.return_value = []
        ensure_main_ci(self.gh)
        self.gh.dispatch.assert_called_once_with("main")
        self.gh.reset_mock()
        self.gh.runs.return_value = [{"head_sha": self.base, "head_branch": "main", "event": "workflow_dispatch"}]
        ensure_main_ci(self.gh)
        self.gh.dispatch.assert_not_called()

    def test_workflow_refresh_restriction_waits_for_dependabot_without_merging(self):
        self.gh.contains.return_value = False
        self.gh.refresh.side_effect = APIError("PUT", "pulls/25/update-branch", 403)
        process(self.gh, 25)
        self.gh.merge.assert_not_called()
        self.gh.dispatch.assert_not_called()

    def test_transient_metadata_failure_is_retried(self):
        responses = [
            SimpleNamespace(returncode=1, stderr="HTTP 502", stdout=""),
            SimpleNamespace(returncode=0, stderr="", stdout='{"default_branch":"main"}'),
        ]
        with patch("merge_dependabot.subprocess.run", side_effect=responses) as command, patch("merge_dependabot.time.sleep"):
            self.assertEqual(GitHub("owner/repo").default, "main")
            self.assertEqual(command.call_count, 2)

    def test_mutating_api_failure_is_not_blindly_retried(self):
        responses = [
            SimpleNamespace(returncode=0, stderr="", stdout='{"default_branch":"main"}'),
            SimpleNamespace(returncode=1, stderr="HTTP 502", stdout=""),
        ]
        with patch("merge_dependabot.subprocess.run", side_effect=responses) as command:
            gh = GitHub("owner/repo")
            with self.assertRaises(APIError):
                gh.dispatch("main")
            self.assertEqual(command.call_count, 2)


if __name__ == "__main__":
    unittest.main()
