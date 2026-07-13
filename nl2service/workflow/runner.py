from dataclasses import dataclass

from nl2service.agent.provider import LLMProvider
from nl2service.spec.models import ServiceSpec
from nl2service.tools.github_tool import GitHubProvider
from nl2service.workflow.graph import NL2ServiceWorkflow
from nl2service.workflow.state import WorkflowState


@dataclass(slots=True)
class WorkflowRun:
    state: WorkflowState


class WorkflowRunner:
    def __init__(
        self,
        model: str | None = None,
        provider: LLMProvider | None = None,
        github_provider: GitHubProvider | None = None,
    ) -> None:
        self.workflow = NL2ServiceWorkflow(model=model, provider=provider, github_provider=github_provider)

    def create(self, user_request: str, additional_context: list[str] | None = None) -> WorkflowRun:
        return WorkflowRun(state=self.workflow.run_create(user_request, additional_context))

    def clarify(self, spec: ServiceSpec) -> WorkflowRun:
        return WorkflowRun(state=self.workflow.run_clarify(spec))

    def render(self, spec: ServiceSpec, out_dir: str | None = None) -> WorkflowRun:
        return WorkflowRun(state=self.workflow.run_render(spec, out_dir))

    def resume(self, state: WorkflowState) -> WorkflowRun:
        return WorkflowRun(state=self.workflow.run_resume(state))

    def resume_with_answers(self, state: WorkflowState, answers: dict[str, str]) -> WorkflowRun:
        resumed = dict(state)
        resumed["interaction"] = {"type": "clarification_answers", "answers": answers}
        resumed["target_phase"] = "resume"
        resumed["error"] = None
        return WorkflowRun(state=self.workflow.run_resume(resumed))

    def resume_with_gate_confirmation(
        self,
        state: WorkflowState,
        confirmed: bool,
        out_dir: str | None = None,
        target_phase: str | None = None,
    ) -> WorkflowRun:
        resumed = dict(state)
        resumed["interaction"] = {"type": "gate_confirmation", "confirmed": confirmed}
        resumed["target_phase"] = target_phase or ("render" if confirmed else resumed.get("target_phase", "draft"))
        resumed["output_dir"] = out_dir
        resumed["error"] = None
        return WorkflowRun(state=self.workflow.run_resume(resumed))

    def resume_with_proto_file(self, state: WorkflowState, proto_file: str) -> WorkflowRun:
        resumed = dict(state)
        resumed["interaction"] = {"type": "proto_submission", "proto_file": proto_file}
        resumed["error"] = None
        return WorkflowRun(state=self.workflow.run_resume(resumed))

    def resume_with_github_delivery(
        self,
        state: WorkflowState,
        owner: str,
        repo: str,
        create_repo: bool = True,
        commit_message: str | None = None,
    ) -> WorkflowRun:
        resumed = dict(state)
        resumed["interaction"] = {
            "type": "github_delivery",
            "payload": {
                "owner": owner,
                "repo": repo,
                "create_repo": create_repo,
                "commit_message": commit_message or "Add generated NL2Service scaffold",
            },
        }
        resumed["target_phase"] = "deliver"
        resumed["error"] = None
        return WorkflowRun(state=self.workflow.run_resume(resumed))
