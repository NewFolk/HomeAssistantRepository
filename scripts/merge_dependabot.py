"""Merge same-repository Dependabot updates only after complete, current CI."""

import json
import os
import re
import subprocess
import time
from urllib.parse import urlencode


class APIError(RuntimeError):
    def __init__(self, method, path, status):
        super().__init__(f"GitHub {method} {path.split('?')[0]} failed (HTTP {status})")
        self.status = status


class GitHub:
    def __init__(self, repo):
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
            raise ValueError("Invalid repository name")
        self.repo = repo
        self.default = self.api("")["default_branch"]

    def api(self, path, data=None, method="GET"):
        args = ["gh", "api", "--method", method, f"repos/{self.repo}/{path}".rstrip("/")]
        if data is not None:
            args += ["--input", "-"]
        for attempt in range(3):
            result = subprocess.run(args, input=json.dumps(data) if data is not None else None,
                                    text=True, capture_output=True, check=False)
            if not result.returncode:
                return json.loads(result.stdout) if result.stdout.strip() else None
            match = re.search(r"HTTP (\d+)", result.stderr)
            status = int(match[1]) if match else 0
            if method == "GET" and status in {429, 500, 502, 503, 504} and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise APIError(method, path, status)

    def open_prs(self):
        page = 1
        while True:
            items = self.api("pulls?" + urlencode({"state": "open", "base": self.default,
                                                 "per_page": 100, "page": page}))
            yield from items
            if len(items) < 100:
                return
            page += 1

    def pr(self, number):
        return self.api(f"pulls/{number}")

    def head(self):
        return self.api(f"git/ref/heads/{self.default}")["object"]["sha"]

    def contains(self, base, head):
        return self.api(f"compare/{base}...{head}")["merge_base_commit"]["sha"] == base

    def refresh(self, number, head):
        self.api(f"pulls/{number}/update-branch", {"expected_head_sha": head}, "PUT")

    def runs(self, head):
        return self.api("actions/workflows/lint.yaml/runs?" + urlencode({
            "head_sha": head, "per_page": 100,
        }))["workflow_runs"]

    def jobs(self, run_id):
        return self.api(f"actions/runs/{run_id}/jobs?filter=latest&per_page=100")

    def create_ref(self, tag, head):
        try:
            existing = self.api(f"git/ref/tags/{tag}")
        except APIError as error:
            if error.status != 404:
                raise
            self.api("git/refs", {"ref": f"refs/tags/{tag}", "sha": head}, "POST")
        else:
            if existing["object"]["sha"] != head:
                raise ValueError("Validation reference moved to another commit")

    def dispatch(self, ref, base=""):
        self.api("actions/workflows/lint.yaml/dispatches", {
            "ref": ref, "inputs": {"google_workspace_baseline_ref": base},
        }, "POST")

    def retry(self, run_id):
        self.api(f"actions/runs/{run_id}/rerun-failed-jobs", {}, "POST")

    def merge(self, number, head):
        result = self.api(f"pulls/{number}/merge", {"sha": head, "merge_method": "squash"}, "PUT")
        if not result["merged"]:
            raise RuntimeError("GitHub did not merge the validated update")

    def delete_ref(self, tag):
        try:
            self.api(f"git/refs/tags/{tag}", method="DELETE")
        except APIError as error:
            if error.status not in {404, 422}:
                raise


def eligible(pr, repo, default):
    return (
        pr.get("state") == "open" and not pr.get("draft", False)
        and pr.get("user", {}).get("login") == "dependabot[bot]"
        and pr.get("base", {}).get("ref") == default
        and (pr.get("head", {}).get("repo") or {}).get("full_name") == repo
    )


def latest_run(runs, pr, tag, repo):
    candidates = []
    for run in runs:
        if run.get("head_sha") != pr["head"]["sha"] or (run.get("head_repository") or {}).get("full_name") != repo:
            continue
        native = run.get("event") == "pull_request" and any(
            item["number"] == pr["number"] for item in run.get("pull_requests", [])
        )
        dispatched = run.get("event") == "workflow_dispatch" and run.get("head_branch") == tag
        if (native or dispatched) and run.get("conclusion") != "action_required":
            candidates.append(run)
    return max(candidates, key=lambda item: item["id"]) if candidates else None


def all_jobs_passed(payload):
    jobs = payload.get("jobs", [])
    return (bool(jobs) and len(jobs) == payload.get("total_count")
            and all(job.get("status") == "completed" and job.get("conclusion") == "success" for job in jobs))


def report(message):
    print(message)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as output:
            output.write(f"- {message}\n")


def process(gh, number):
    pr = gh.pr(number)
    if not eligible(pr, gh.repo, gh.default):
        return
    base, head = gh.head(), pr["head"]["sha"]
    if not gh.contains(base, head):
        try:
            gh.refresh(number, head)
        except APIError as error:
            if error.status != 403:
                raise
            report(f"PR #{number}: GitHub refused the branch refresh; waiting for Dependabot's automatic rebase")
            return
        for _ in range(10):
            updated = gh.pr(number)
            if not eligible(updated, gh.repo, gh.default):
                return
            if updated["head"]["sha"] != head and gh.contains(base, updated["head"]["sha"]):
                pr, head = updated, updated["head"]["sha"]
                break
            time.sleep(1)
        else:
            report(f"PR #{number}: branch refresh queued; the next scan will continue")
            return
    tag = f"automation/dependabot-ci/{number}/{base[:16]}-{head[:16]}"
    run = latest_run(gh.runs(head), pr, tag, gh.repo)
    if run is None:
        gh.create_ref(tag, head)
        gh.dispatch(tag, base)
        report(f"PR #{number}: full CI and upgrade tests dispatched for the exact updated head")
        return
    if run["status"] != "completed":
        report(f"PR #{number}: waiting for CI run {run['id']}")
        return
    if run["conclusion"] != "success":
        if run["conclusion"] in {"failure", "timed_out", "startup_failure"} and run.get("run_attempt", 1) < 2:
            gh.retry(run["id"])
            report(f"PR #{number}: retrying failed CI jobs once")
        else:
            report(f"PR #{number}: CI has not passed; publication is held")
        return
    if not all_jobs_passed(gh.jobs(run["id"])):
        report(f"PR #{number}: waiting for all CI jobs to report success")
        return
    current = gh.pr(number)
    if not eligible(current, gh.repo, gh.default) or current["head"]["sha"] != head or gh.head() != base:
        report(f"PR #{number}: base or head changed; the next scan will revalidate")
        return
    gh.merge(number, head)
    gh.dispatch(gh.default)
    gh.delete_ref(tag)
    report(f"PR #{number}: tested head merged and published-main CI dispatched")


def ensure_main_ci(gh):
    head = gh.head()
    if not any(run.get("head_sha") == head and run.get("head_branch") == gh.default
               and run.get("event") in {"push", "workflow_dispatch"} for run in gh.runs(head)):
        gh.dispatch(gh.default)
        report("Published-main CI was missing and has been dispatched")


def main():
    gh = GitHub(os.environ["GH_REPO"])
    for item in gh.open_prs():
        if eligible(item, gh.repo, gh.default):
            try:
                process(gh, item["number"])
            except APIError as error:
                if error.status not in {409, 422}:
                    raise
                report(f"PR #{item['number']}: branch changed or needs conflict resolution; publication is held")
    ensure_main_ci(gh)


if __name__ == "__main__":
    main()
