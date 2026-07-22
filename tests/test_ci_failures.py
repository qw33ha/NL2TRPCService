from __future__ import annotations

from nl2service.tools.github_tool import WorkflowJobRef, WorkflowRunRef
from nl2service.workflow.nodes.delivery import GitHubActionsNodes
from nl2service.workflow.state import structured_state_defaults


class FailedWorkflowProvider:
    logs = "2026-07-16T12:00:00Z ##[error]build failed at 3dac0c4e075df112a0ab681c84ef842b4461f354"

    def get_workflow_run_for_commit(self, owner: str, repo: str, commit_sha: str) -> WorkflowRunRef:
        return WorkflowRunRef("42", "completed", "failure", commit_sha, "https://example.invalid/run/42")

    def get_workflow_jobs(self, owner: str, repo: str, run_id: str) -> list[WorkflowJobRef]:
        return [WorkflowJobRef("7", "build", "completed", "failure")]

    def get_workflow_logs(self, owner: str, repo: str, run_id: str) -> str:
        return self.logs


def test_failure_signature_ignores_timestamp_and_commit_sha() -> None:
    first = "2026-07-16T12:00:00Z ##[error]build failed at 3dac0c4e075df112a0ab681c84ef842b4461f354"
    second = "2026-07-17T09:30:00Z ##[error]build failed at 24ef8292eb623e19f6b87a5109dc85f98c761f2d"

    assert GitHubActionsNodes._signature_source(first) == GitHubActionsNodes._signature_source(second)


def test_repeated_ci_failure_stops_the_repair_loop() -> None:
    provider = FailedWorkflowProvider()
    nodes = GitHubActionsNodes(provider)  # type: ignore[arg-type]
    signature_source = nodes._signature_source(provider.logs)
    import hashlib

    signature = hashlib.sha256(f"github_ci\nbuild\n{signature_source}".encode()).hexdigest()
    state = {
        **structured_state_defaults(),
        "github_delivery": {"owner": "example", "repo": "service", "commit_sha": "abc1234"},
        "repair_history": [{"source": "github_ci", "signature": signature}],
        "status": "awaiting_github_actions",
        "error": None,
    }

    result = nodes.monitor(state)  # type: ignore[arg-type]

    assert result["status"] == "error"
    assert "repeated after an automatic repair" in str(result["error"])
