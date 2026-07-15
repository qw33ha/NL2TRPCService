from __future__ import annotations

import re

from nl2service.tools.github_tool import GitHubAPIError, GitHubProvider
from nl2service.workflow.state import WorkflowState


class GitHubActionsNodes:
    def __init__(self, provider: GitHubProvider, max_repair_attempts: int = 3) -> None:
        self.provider = provider
        self.max_repair_attempts = max_repair_attempts

    def monitor(self, state: WorkflowState) -> WorkflowState:
        delivery = state.get("github_delivery", {})
        owner = str(delivery.get("owner") or "").strip()
        repo = str(delivery.get("repo") or "").strip()
        commit_sha = str(delivery.get("commit_sha") or "").strip()
        if not owner or not repo or not commit_sha:
            return self._error(state, "GitHub Actions monitoring requires owner, repo, and commit SHA.")

        try:
            run = self.provider.get_workflow_run_for_commit(owner, repo, commit_sha)
            polls = int(state.get("ci_run", {}).get("poll_attempts", 0)) + 1
            if run is None or run.status != "completed":
                state["ci_run"] = {
                    "run_id": run.run_id if run else None,
                    "url": run.url if run else None,
                    "commit_sha": commit_sha,
                    "status": run.status if run else "waiting_for_run",
                    "conclusion": run.conclusion if run else None,
                    "failed_job": None,
                    "logs": None,
                    "poll_attempts": polls,
                }
                state["interaction"] = None
                if polls >= 30:
                    return self._error(
                        state,
                        "No completed GitHub Actions run was found for the delivered commit after 30 checks.",
                    )
                state["status"] = "awaiting_github_actions"
                state["error"] = None
                return state

            if run.conclusion == "success":
                return self._record_success(state, owner, repo, commit_sha, run, polls)
            return self._record_failure(state, owner, repo, commit_sha, run, polls)
        except GitHubAPIError as exc:
            return self._error(state, str(exc))

    def _record_success(self, state, owner, repo, commit_sha, run, polls):
        spec = state.get("draft_spec")
        namespace = spec.deploy.namespace if spec else None
        success_logs = self.provider.get_workflow_logs(owner, repo, run.run_id)
        digest_match = re.search(r"digest:\s*(sha256:[0-9a-f]{64})", success_logs)
        state["ci_run"] = {
            "run_id": run.run_id,
            "url": run.url,
            "commit_sha": commit_sha,
            "status": run.status,
            "conclusion": run.conclusion,
            "failed_job": None,
            "logs": None,
            "poll_attempts": polls,
        }
        state["deployment"] = {
            "status": "succeeded",
            "environment": namespace,
            "namespace": namespace,
            "deployment": spec.service.name if spec else None,
            "image": f"ghcr.io/{owner}/{repo}:{commit_sha}",
            "image_digest": digest_match.group(1) if digest_match else None,
            "endpoint": spec.exposure.host if spec else None,
        }
        state["active_failure"] = None
        state["status"] = "deployment_succeeded"
        state["error"] = None
        return state

    def _record_failure(self, state, owner, repo, commit_sha, run, polls):
        jobs = self.provider.get_workflow_jobs(owner, repo, run.run_id)
        failed = next((job for job in jobs if job.conclusion == "failure"), None)
        failed_stage = failed.name if failed else "github_actions"
        source = "deployment" if failed_stage.lower() == "deploy" else "github_ci"
        logs = self.provider.get_workflow_logs(owner, repo, run.run_id)[-120_000:]
        state["ci_run"] = {
            "run_id": run.run_id,
            "url": run.url,
            "commit_sha": commit_sha,
            "status": run.status,
            "conclusion": run.conclusion,
            "failed_job": failed_stage,
            "logs": logs,
            "poll_attempts": polls,
        }
        state["active_failure"] = {
            "source": source,
            "stage": failed_stage,
            "command": None,
            "exit_code": 1,
            "logs": logs,
            "run_id": run.run_id,
            "commit_sha": commit_sha,
        }
        prior = [item for item in state.get("repair_history", []) if item.get("source") == source]
        if len(prior) >= self.max_repair_attempts:
            return self._error(
                state,
                f"{source}/{failed_stage} failed after {self.max_repair_attempts} repairs.",
            )
        state["status"] = "github_actions_failed"
        state["error"] = None
        return state

    @staticmethod
    def route(state: WorkflowState) -> str:
        if state.get("status") == "github_actions_failed":
            return "repair_build_errors"
        if state.get("status") == "deployment_succeeded":
            return "prepare_delivery_report"
        return "end"

    @staticmethod
    def prepare_report(state: WorkflowState) -> WorkflowState:
        spec = state.get("draft_spec")
        if spec is None:
            return GitHubActionsNodes._error(state, "No spec available for the delivery report.")
        delivery = state.get("github_delivery", {})
        ci_run = state.get("ci_run", {})
        deployment = state.get("deployment", {})
        state["delivery_report"] = {
            "repository_url": delivery.get("repository_url"),
            "branch": delivery.get("branch"),
            "commit_sha": delivery.get("commit_sha"),
            "action_run_url": ci_run.get("url"),
            "image": deployment.get("image"),
            "image_digest": deployment.get("image_digest"),
            "environment": deployment.get("environment"),
            "deployment": deployment.get("deployment"),
            "endpoint": deployment.get("endpoint"),
            "secret_names": [
                name for name in [spec.database.secret_name, spec.kafka.secret_name] if name
            ],
            "database_tables": [
                spec.database.database
            ] if spec.database.enabled and spec.database.database else [],
            "kafka_topics": [spec.kafka.topic] if spec.kafka.enabled and spec.kafka.topic else [],
            "usage_examples": [f"{endpoint.method} {endpoint.path}" for endpoint in spec.endpoints],
            "warnings": [],
        }
        state["status"] = "complete"
        state["error"] = None
        return state

    @staticmethod
    def _error(state: WorkflowState, message: str) -> WorkflowState:
        state["status"] = "error"
        state["error"] = message
        return state
