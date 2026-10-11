"""Explicit opt-in remote CI fault/repair experiment on an isolated test branch."""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import quote

from nl2service.evaluation.runner import BlockedDelivery, MeasuredProvider, UsageTracker
from nl2service.spec.models import ServiceSpec
from nl2service.tools.github_tool import GitHubApiProvider
from nl2service.workflow.core import WorkflowCore
from nl2service.workflow.nodes.delivery import GitHubActionsNodes


WORKFLOW = '''name: evaluation-ci
on:
  push:
    branches: ["evaluation/cicd-*"]
permissions:
  contents: read
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-go@v6
        with:
          go-version: "1.25.x"
          cache: false
      - run: go mod tidy
      - run: go vet ./...
      - run: go test ./...
      - run: go build ./...
  container:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - run: docker build -t nl2service-evaluation:local .
'''
WORKFLOW_PATH = ".github/workflows/build-and-deploy.yaml"
FAULT_PATH = "handler/evaluation_ci_fault.go"


def validate_target(repository, branch):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) or any(p in {".", ".."} for p in repository.split("/")):
        raise ValueError("Repository must be owner/repo")
    if not branch.startswith("evaluation/cicd-") or any(c in branch for c in " ~^:?*[\\") or ".." in branch:
        raise ValueError("Remote CI requires an isolated evaluation/cicd-* branch")


def guard_workflows(files):
    paths = {p for p in files if p.startswith(".github/workflows/")}
    if paths != {WORKFLOW_PATH} or files.get(WORKFLOW_PATH) != WORKFLOW:
        raise ValueError("Remote evaluation permits only its fixed CI-only workflow")


def run(repository, branch, report_path):
    validate_target(repository, branch)
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is required")
    api = GitHubApiProvider(token=token, api_base_url="https://api.github.com", server_url="https://github.com")
    prefix = f"/repos/{repository}"
    def request(method, suffix, payload=None):
        return api._request_json(method, prefix + suffix, payload)
    meta = request("GET", "")
    base = request("GET", "/git/ref/heads/" + quote(meta["default_branch"], safe=""))["object"]["sha"]
    existing = request("GET", "/branches?per_page=100")
    if any(b["name"] == branch for b in existing):
        raise ValueError("Evaluation branch already exists; choose a fresh name")
    base_commit = request("GET", "/git/commits/" + base)
    tree = request("GET", "/git/trees/" + base_commit["tree"]["sha"] + "?recursive=1")
    if tree.get("truncated"):
        raise ValueError("Repository tree truncated")
    files = {}
    for item in tree["tree"]:
        if item["type"] != "blob":
            continue
        blob = request("GET", "/git/blobs/" + item["sha"])
        files[item["path"]] = base64.b64decode(blob["content"]).decode("utf-8")
    if {p for p in files if p.startswith(".github/workflows/")} != {WORKFLOW_PATH}:
        raise ValueError("Inspect extra workflows before remote evaluation")
    files[WORKFLOW_PATH] = WORKFLOW
    files[FAULT_PATH] = "package handler\nvar evaluationCIFault = missingEvaluationCISymbol\n"
    guard_workflows(files)
    report = {"mode": "real GitHub Actions with declared compiler fault and production repair nodes",
              "repository": repository, "branch": branch, "base_sha": base,
              "deployment_executed": False, "image_published": False, "complete": False, "runs": []}
    def save():
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    save()
    def commit(parent, updated, message):
        guard_workflows(updated)
        parent_tree = request("GET", "/git/commits/" + parent)["tree"]["sha"]
        # Inline content creates only evaluation changes; never update default branch.
        changes = [{"path": p, "mode": "100644", "type": "blob", "content": content}
                   for p, content in updated.items() if files_at_parent.get(p) != content]
        if not changes:
            new_tree = parent_tree
        else:
            new_tree = request("POST", "/git/trees", {"base_tree": parent_tree, "tree": changes})["sha"]
        return request("POST", "/git/commits", {"message": message, "tree": new_tree, "parents": [parent]})["sha"]
    files_at_parent = {**files}
    files_at_parent.pop(FAULT_PATH)
    original_workflow = request("GET", "/contents/" + WORKFLOW_PATH + "?ref=" + base)
    files_at_parent[WORKFLOW_PATH] = base64.b64decode(original_workflow["content"]).decode()
    initial_sha = commit(base, files, "test: isolate CI and inject declared compiler fault")
    request("POST", "/git/refs", {"ref": "refs/heads/" + branch, "sha": initial_sha})
    report["initial_sha"] = initial_sha
    save()
    print("Created isolated evaluation branch:", branch, flush=True)
    def wait(sha):
        last = None
        for _ in range(120):
            data = request("GET", "/actions/runs?head_sha=" + sha + "&branch=" + quote(branch, safe="") + "&per_page=20")
            candidates = [r for r in data["workflow_runs"] if r["head_sha"] == sha and r["name"] == "evaluation-ci"]
            if candidates:
                current = candidates[0]
                state = (current["id"], current["status"], current["conclusion"])
                if state != last:
                    print("Actions:", current["html_url"], current["status"], current["conclusion"], flush=True)
                    last = state
                if current["status"] == "completed":
                    jobs = request("GET", f"/actions/runs/{current['id']}/jobs?per_page=100")["jobs"]
                    observed = {"id": current["id"], "sha": sha, "url": current["html_url"], "status": current["status"], "conclusion": current["conclusion"],
                                "jobs": [{"name": j["name"], "status": j["status"], "conclusion": j["conclusion"]} for j in jobs]}
                    report["runs"].append(observed)
                    save()
                    return observed
            time.sleep(5)
        raise TimeoutError("No completed evaluation CI run after ten minutes")
    failed = wait(initial_sha)
    if failed["conclusion"] != "failure" or not any(j["name"] == "build" and j["conclusion"] == "failure" for j in failed["jobs"]):
        raise RuntimeError("Expected injected build failure was not observed")
    spec = ServiceSpec.model_validate({"service": {"name": "simple-service", "mode": "http", "module": "github.com/" + repository},
                                     "endpoints": [{"path": "/health", "method": "GET"}], "deploy": {"enabled": False}})
    state = {"draft_spec": spec, "rendered_files": files, "model": "gpt-4.1-mini-2025-04-14",
             "user_request": "Preserve the existing application. Repair the compiler failure reported by CI.",
             "github_delivery": {"owner": repository.split('/')[0], "repo": repository.split('/')[1], "commit_sha": initial_sha}, "repair_history": []}
    state = GitHubActionsNodes(api).monitor(state)
    if state.get("status") != "github_actions_failed":
        raise RuntimeError(state.get("error") or "CI did not route to repair")
    report["failure"] = state["active_failure"]
    tracker = UsageTracker()
    core = WorkflowCore(model=state["model"], provider=MeasuredProvider(tracker), github_provider=BlockedDelivery())
    for attempt in range(3):
        state = core._repair_build_errors_node(state)
        if state.get("status") == "error":
            raise RuntimeError(state["error"])
        guard_workflows(state["rendered_files"])
        state = core._verify_build_node(state)
        if state.get("status") == "verified":
            break
    else:
        raise RuntimeError("Repaired project did not pass local verification")
    report["repair_history"] = state.get("repair_history", [])
    report["model_calls"] = tracker.calls
    report["local_repaired_build"] = state["local_build"]
    save()
    files_at_parent = files
    fixed_sha = commit(initial_sha, state["rendered_files"], "fix: apply agent repair from evaluation CI diagnostics")
    current_head = request("GET", "/git/ref/heads/" + quote(branch, safe=""))["object"]["sha"]
    if current_head != initial_sha:
        raise RuntimeError("Evaluation branch moved unexpectedly")
    request("PATCH", "/git/refs/heads/" + quote(branch, safe=""), {"sha": fixed_sha, "force": False})
    report["repaired_sha"] = fixed_sha
    save()
    success = wait(fixed_sha)
    report["complete"] = True
    report["passed"] = success["conclusion"] == "success" and all(any(j["name"] == name and j["conclusion"] == "success" for j in success["jobs"]) for name in ["build", "container"])
    report["default_branch_unchanged"] = request("GET", "/git/ref/heads/" + quote(meta["default_branch"], safe=""))["object"]["sha"] == base
    save()
    print("Remote CI recovery:", report["passed"], flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--execute", action="store_true", help="Explicitly create remote evaluation branch and run Actions")
    args = parser.parse_args()
    if not args.execute:
        parser.error("Remote mutation requires explicit --execute")
    try:
        result = run(args.repository, args.branch, args.report)
    except Exception as exc:
        result = json.loads(args.report.read_text()) if args.report.exists() else {"repository": args.repository, "branch": args.branch}
        result.update(complete=False, error=str(exc))
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2), encoding="utf-8")
        raise
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
