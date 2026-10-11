"""Isolated CI/CD graph evaluation. All GitHub effects are in-memory fixtures."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from langgraph.types import Command

from nl2service.evaluation.runner import ReplayProvider, load_tasks
from nl2service.build.verify import GoBuildVerifier
from nl2service.render.renderer import ServiceRenderer
from nl2service.runtime.checkpointer import SQLiteCheckpointRuntime
from nl2service.spec.models import ServiceSpec
from nl2service.tools.github_tool import GitHubAPIError, GitHubDeliveryResult, WorkflowJobRef, WorkflowRunRef
from nl2service.workflow.conversation_graph import ConversationalServiceWorkflow
from nl2service.workflow.core import WorkflowCore


SCENARIOS = [
    {"id": "ci-success", "expected": "complete"},
    {"id": "ci-wait-success", "expected": "complete"},
    {"id": "ci-repair-success", "expected": "complete", "repair_source": "github_ci"},
    {"id": "ci-repeat-stop", "expected": "error", "repair_source": "github_ci", "error_contains": "repeated"},
    {"id": "ci-timeout", "expected": "error", "error_contains": "30 checks"},
    {"id": "ci-api-error", "expected": "error", "error_contains": "403"},
    {"id": "cd-success", "expected": "complete", "deploy": True},
    {"id": "cd-failure-stop", "expected": "error", "deploy": True, "repair_source": "deployment", "error_contains": "repeated"},
    {"id": "cd-skipped-rejected", "expected": "error", "deploy": True, "error_contains": "unverified"},
]


class FixtureGitHub:
    """No network API or real credentials; preserve commit/run identity."""
    def __init__(self, scenario):
        self.scenario = scenario
        self.commits = []
        self.polls = 0
        self.commit_sha = None

    def create_repo(self, *args):
        raise AssertionError("Evaluation must not create a repository")

    def commit_files(self, repository_full_name, files, message=""):
        if repository_full_name != "evaluation/isolated":
            raise AssertionError("Unexpected evaluation repository")
        sha = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()[:40]
        self.commits.append({"sha": sha, "files": dict(files)})
        self.commit_sha = sha
        return GitHubDeliveryResult(repository_full_name, "https://example.invalid/evaluation/isolated", "evaluation", sha)

    def get_workflow_run_for_commit(self, owner, repo, sha):
        assert (owner, repo, sha) == ("evaluation", "isolated", self.commit_sha)
        self.polls += 1
        name = self.scenario["id"]
        if name == "ci-api-error":
            raise GitHubAPIError("Fixture GitHub API (403): access denied")
        if name == "ci-timeout":
            return None
        if name == "ci-wait-success" and self.polls == 1:
            return WorkflowRunRef("fixture", "in_progress", None, sha)
        failed = name in {"ci-repeat-stop", "cd-failure-stop"} or (name == "ci-repair-success" and len(self.commits) == 1)
        return WorkflowRunRef("fixture", "completed", "failure" if failed else "success", sha, "https://example.invalid/run/fixture")

    def get_workflow_jobs(self, *args):
        name = self.scenario["id"]
        if name == "cd-failure-stop":
            return [WorkflowJobRef("job", "deploy", "completed", "failure")]
        if name == "cd-success":
            return [WorkflowJobRef("job", "deploy", "completed", "success")]
        if name == "cd-skipped-rejected":
            return [WorkflowJobRef("job", "deploy", "completed", "skipped")]
        return [WorkflowJobRef("job", "build", "completed", "failure")]

    def get_workflow_logs(self, *args):
        if self.scenario["id"].startswith("cd-") and self.scenario["id"] != "cd-success":
            return "##[error]deployment rollout failed"
        return "##[error]build failed" if self.scenario["id"] in {"ci-repair-success", "ci-repeat-stop"} else "digest: sha256:" + "a" * 64


class RepairReplay(ReplayProvider):
    """Controlled changed output exercises routing; does not measure LLM competence."""
    def with_structured_output(self, schema, **kwargs):
        if schema.__name__ != "RefinedRender":
            return super().with_structured_output(schema, **kwargs)
        class Response:
            def invoke(self, messages):
                return schema(files={"handler/ci_repair.go": "package handler\n// controlled CI feedback repair\n"})
        return Response()


def run_scenario(scenario, seed_files, spec, verifier=None):
    spec = spec.model_copy(deep=True)
    spec.deploy.enabled = bool(scenario.get("deploy"))
    spec.deploy.namespace = "evaluation"
    provider = FixtureGitHub(scenario)
    core = WorkflowCore(provider=RepairReplay(spec.model_dump()), github_provider=provider)
    if verifier is not None:
        core.verifier = verifier
    trace, interrupts = [], []
    with TemporaryDirectory(prefix="nl2service-ci-eval-") as directory:
        root = Path(directory)
        core.renderer.write_tree(seed_files, root / "project")
        with SQLiteCheckpointRuntime(root / "checkpoint.db") as runtime:
            config = {"configurable": {"thread_id": scenario["id"]}, "recursion_limit": 100}
            graph = ConversationalServiceWorkflow(core, runtime.checkpointer).graph
            graph.update_state(config, {"draft_spec": spec, "rendered_files": seed_files,
                "status": "verified", "output_dir": str(root / "project"), "repair_history": [],
                "github_delivery": {"owner": "evaluation", "repo": "isolated", "create_repo": False}}, as_node="verify_build")
            payload = None
            for _ in range(40):
                for update in graph.stream(payload, config, stream_mode="updates"):
                    trace.extend({"node": node, "status": value.get("status")} for node, value in update.items() if node != "__interrupt__")
                snapshot = graph.get_state(config)
                pending = [i for t in snapshot.tasks for i in t.interrupts]
                if not pending:
                    break
                assert pending[0].value["kind"] == "external_wait"
                interrupts.append("external_wait")
                graph = ConversationalServiceWorkflow(core, runtime.checkpointer).graph
                payload = Command(resume={"type": "poll"})
            else:
                raise RuntimeError("CI evaluation exceeded bounded polling")
            state = graph.get_state(config).values
    history = state.get("repair_history", [])
    checks = {"expected_status": state.get("status") == scenario["expected"],
              "exact_commit": all(c["sha"] for c in provider.commits) and state.get("github_delivery", {}).get("commit_sha") == provider.commit_sha,
              "error_detail": scenario.get("error_contains", "") in (state.get("error") or ""),
              "repair_feedback": not scenario.get("repair_source") or any(h["source"] == scenario["repair_source"] and h["changed_files"] and h["feedback"] for h in history)}
    if scenario["expected"] == "complete":
        checks["delivery_report"] = state.get("delivery_report", {}).get("commit_sha") == provider.commit_sha
        checks["deployment_status"] = state.get("deployment", {}).get("status") == ("succeeded" if scenario.get("deploy") else "skipped")
    if scenario["id"] == "ci-repair-success":
        checks["recommit"] = len(provider.commits) == 2 and provider.commits[0]["sha"] != provider.commits[1]["sha"]
    if scenario["id"] == "ci-timeout":
        checks["bounded_polls"] = provider.polls == 30
    return {"id": scenario["id"], "passed": all(checks.values()), "checks": checks,
            "status": state.get("status"), "error": state.get("error"), "trace": trace,
            "polls": provider.polls, "checkpoint_restarts": len(interrupts),
            "commits": [c["sha"] for c in provider.commits], "repair_history": history,
            "ci_run": state.get("ci_run"), "deployment": state.get("deployment")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    task = load_tasks(Path(__file__).with_name("tasks-v1.jsonl"))[0]
    spec = ServiceSpec.model_validate(task.spec)
    files = ServiceRenderer().render_tree(spec)
    initial = GoBuildVerifier().verify(files)
    if not initial.success:
        raise RuntimeError(initial.feedback)
    files = initial.synchronized_files or files
    results = [run_scenario(s, files, spec) for s in SCENARIOS]
    report = {"mode": "isolated CI/CD graph with fixture GitHub and controlled repair; real local Go verification",
              "remote_actions_executed": False, "docker_executed": False, "cluster_deployment_executed": False,
              "initial_build_passed": initial.success, "passed": sum(r["passed"] for r in results), "total": len(results), "results": results}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"CI/CD graph checks: {report['passed']}/{report['total']}; remote execution: false")
    raise SystemExit(0 if all(r["passed"] for r in results) else 1)


if __name__ == "__main__":
    main()
