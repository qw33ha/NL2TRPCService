from __future__ import annotations

from pathlib import Path

from langgraph.graph import END, START, StateGraph

from nl2service.agent.code_refiner import CodeRefinerAgent, CodeRefinerError
from nl2service.agent.provider import LLMProvider
from nl2service.agent.session import ClarificationTurn, MainAgentSessionState
from nl2service.agent.spec_builder import SpecBuilderAgent
from nl2service.build.verify import GoBuildVerifier
from nl2service.render.renderer import ProtoContractError, ServiceRenderer
from nl2service.spec.models import ServiceSpec
from nl2service.spec.validator import ServiceSpecValidator
from nl2service.tools.github_tool import GitHubAPIError, GitHubApiProvider, GitHubProvider
from nl2service.workflow.clarify import ClarificationSessionBuilder
from nl2service.workflow.gate import GateSummaryBuilder
from nl2service.workflow.state import WorkflowState, clarification_to_dict, issue_to_dict
from nl2service.workflow.updates import apply_field_updates

MAX_BUILD_REPAIR_ATTEMPTS = 2


class NL2ServiceWorkflow:
    def __init__(
        self,
        model: str | None = None,
        provider: LLMProvider | None = None,
        github_provider: GitHubProvider | None = None,
    ) -> None:
        self.model = model
        self.provider = provider or LLMProvider()
        self.github_provider = github_provider or GitHubApiProvider()
        self.validator = ServiceSpecValidator()
        self.clarifier = ClarificationSessionBuilder(self.validator)
        self.gate_builder = GateSummaryBuilder()
        self.renderer = ServiceRenderer()
        self.verifier = GoBuildVerifier()
        self.graph = self._build_graph().compile()

    def run_create(self, user_request: str, additional_context: list[str] | None = None) -> WorkflowState:
        return self.graph.invoke(
            {
                "user_request": user_request,
                "model": self.model,
                "target_phase": "draft",
                "additional_context": additional_context or [],
                "clarification_history": [],
                "notes": [],
                "extracted_fields": [],
                "gate_confirmed": False,
                "interaction": None,
                "validation_issues": [],
                "clarification_items": [],
                "gate_summary_lines": [],
                "proto_summary_lines": [],
                "verification_summary_lines": [],
                "build_feedback": None,
                "verification_attempts": 0,
                "rendered_files": {},
                "refinement_notes": [],
                "output_dir": None,
                "github_delivery": {},
                "github_summary_lines": [],
                "status": "starting",
                "error": None,
            }
        )

    def run_clarify(self, spec: ServiceSpec) -> WorkflowState:
        return self.graph.invoke(
            {
                "user_request": "",
                "model": self.model,
                "target_phase": "clarify",
                "additional_context": [],
                "clarification_history": [],
                "notes": [],
                "extracted_fields": [],
                "gate_confirmed": False,
                "interaction": None,
                "draft_spec": spec,
                "validation_issues": [],
                "clarification_items": [],
                "gate_summary_lines": [],
                "proto_summary_lines": [],
                "verification_summary_lines": [],
                "build_feedback": None,
                "verification_attempts": 0,
                "rendered_files": {},
                "refinement_notes": [],
                "output_dir": None,
                "github_delivery": {},
                "github_summary_lines": [],
                "status": "starting",
                "error": None,
            }
        )

    def run_render(self, spec: ServiceSpec, out_dir: str | None = None) -> WorkflowState:
        return self.graph.invoke(
            {
                "user_request": "",
                "model": self.model,
                "target_phase": "render",
                "additional_context": [],
                "clarification_history": [],
                "notes": [],
                "extracted_fields": [],
                "gate_confirmed": True,
                "interaction": {"type": "gate_confirmation", "confirmed": True},
                "draft_spec": spec,
                "validation_issues": [],
                "clarification_items": [],
                "gate_summary_lines": [],
                "proto_summary_lines": [],
                "verification_summary_lines": [],
                "build_feedback": None,
                "verification_attempts": 0,
                "rendered_files": {},
                "refinement_notes": [],
                "output_dir": out_dir,
                "github_delivery": {},
                "github_summary_lines": [],
                "status": "starting",
                "error": None,
            }
        )

    def run_resume(self, state: WorkflowState) -> WorkflowState:
        return self.graph.invoke(state)

    def _build_graph(self) -> StateGraph:
        graph = StateGraph(WorkflowState)
        graph.add_node("build_spec", self._build_spec_node)
        graph.add_node("validate_spec", self._validate_spec_node)
        graph.add_node("await_clarification", self._await_clarification_node)
        graph.add_node("apply_clarification", self._apply_clarification_node)
        graph.add_node("prepare_gate", self._prepare_gate_node)
        graph.add_node("await_gate_confirmation", self._await_gate_confirmation_node)
        graph.add_node("apply_gate_confirmation", self._apply_gate_confirmation_node)
        graph.add_node("ensure_proto", self._ensure_proto_node)
        graph.add_node("await_proto", self._await_proto_node)
        graph.add_node("apply_proto_submission", self._apply_proto_submission_node)
        graph.add_node("render_project", self._render_project_node)
        graph.add_node("refine_code", self._refine_code_node)
        graph.add_node("verify_build", self._verify_build_node)
        graph.add_node("repair_build_errors", self._repair_build_errors_node)
        graph.add_node("prepare_github_delivery", self._prepare_github_delivery_node)
        graph.add_node("await_github_delivery", self._await_github_delivery_node)
        graph.add_node("apply_github_delivery", self._apply_github_delivery_node)
        graph.add_node("deliver_to_github", self._deliver_to_github_node)

        graph.add_conditional_edges(
            START,
            self._route_start,
            {
                "build_spec": "build_spec",
                "validate_spec": "validate_spec",
                "apply_clarification": "apply_clarification",
                "apply_gate_confirmation": "apply_gate_confirmation",
                "apply_proto_submission": "apply_proto_submission",
                "apply_github_delivery": "apply_github_delivery",
            },
        )
        graph.add_edge("build_spec", "validate_spec")
        graph.add_conditional_edges(
            "validate_spec",
            self._route_after_validate,
            {
                "await_clarification": "await_clarification",
                "prepare_gate": "prepare_gate",
            },
        )
        graph.add_conditional_edges(
            "apply_clarification",
            self._route_after_apply_clarification,
            {
                "await_clarification": "await_clarification",
                "prepare_gate": "prepare_gate",
            },
        )
        graph.add_edge("prepare_gate", "await_gate_confirmation")
        graph.add_conditional_edges(
            "await_gate_confirmation",
            self._route_after_gate_wait,
            {
                "ensure_proto": "ensure_proto",
                "end": END,
            },
        )
        graph.add_conditional_edges(
            "apply_gate_confirmation",
            self._route_after_apply_gate_confirmation,
            {
                "ensure_proto": "ensure_proto",
                "end": END,
            },
        )
        graph.add_conditional_edges(
            "ensure_proto",
            self._route_after_ensure_proto,
            {
                "await_proto": "await_proto",
                "render_project": "render_project",
            },
        )
        graph.add_edge("apply_proto_submission", "ensure_proto")
        graph.add_edge("render_project", "refine_code")
        graph.add_edge("refine_code", "verify_build")
        graph.add_conditional_edges(
            "verify_build",
            self._route_after_verify_build,
            {
                "repair_build_errors": "repair_build_errors",
                "prepare_github_delivery": "prepare_github_delivery",
                "end": END,
            },
        )
        graph.add_edge("repair_build_errors", "verify_build")
        graph.add_edge("prepare_github_delivery", "await_github_delivery")
        graph.add_edge("await_clarification", END)
        graph.add_edge("await_proto", END)
        graph.add_edge("await_github_delivery", END)
        graph.add_edge("apply_github_delivery", "deliver_to_github")
        graph.add_edge("deliver_to_github", END)
        return graph

    def _route_start(self, state: WorkflowState) -> str:
        interaction = state.get("interaction") or {}
        interaction_type = interaction.get("type")
        if interaction_type == "clarification_answers":
            return "apply_clarification"
        if interaction_type == "gate_confirmation":
            return "apply_gate_confirmation"
        if interaction_type == "proto_submission":
            return "apply_proto_submission"
        if interaction_type == "github_delivery":
            return "apply_github_delivery"
        if state.get("draft_spec") is not None:
            return "validate_spec"
        return "build_spec"

    def _build_spec_node(self, state: WorkflowState) -> WorkflowState:
        session = MainAgentSessionState(
            user_request=state.get("user_request", ""),
            draft_spec=state.get("draft_spec"),
            additional_context=list(state.get("additional_context", [])),
            clarification_history=[ClarificationTurn(**turn) for turn in state.get("clarification_history", [])],
            rendered_files=dict(state.get("rendered_files", {})),
        )
        result = SpecBuilderAgent(model=state.get("model"), provider=self.provider).build_from_session(session)
        state["draft_spec"] = result.spec
        state["notes"] = result.notes
        state["extracted_fields"] = result.extracted_fields
        state["model"] = result.model
        state["interaction"] = None
        state["status"] = "draft_built"
        state["error"] = None
        return state

    def _validate_spec_node(self, state: WorkflowState) -> WorkflowState:
        spec = state.get("draft_spec")
        if spec is None:
            state["status"] = "error"
            state["error"] = "No draft spec available for validation."
            return state
        result = self.validator.validate(spec)
        state["validation_issues"] = [issue_to_dict(issue) for issue in result.issues]
        state["status"] = "validated"
        state["error"] = None
        return state

    def _route_after_validate(self, state: WorkflowState) -> str:
        if state.get("error"):
            return "await_clarification"
        issues = state.get("validation_issues", [])
        if any(issue.get("severity") == "error" for issue in issues):
            return "await_clarification"
        return "prepare_gate"

    def _await_clarification_node(self, state: WorkflowState) -> WorkflowState:
        spec = state.get("draft_spec")
        if spec is None:
            state["clarification_items"] = []
            state["status"] = "awaiting_clarification"
            return state
        session = self.clarifier.build(spec)
        state["clarification_items"] = [clarification_to_dict(item) for item in session.items]
        state["interaction"] = None
        state["status"] = "awaiting_clarification"
        return state

    def _apply_clarification_node(self, state: WorkflowState) -> WorkflowState:
        spec = state.get("draft_spec")
        interaction = state.get("interaction") or {}
        answers = interaction.get("answers", {})
        if spec is None:
            state["status"] = "error"
            state["error"] = "No draft spec available for clarification updates."
            return state
        state["draft_spec"] = apply_field_updates(spec, answers)
        state["clarification_items"] = []
        state["interaction"] = None
        state["status"] = "clarification_applied"
        return self._validate_spec_node(state)

    def _route_after_apply_clarification(self, state: WorkflowState) -> str:
        return self._route_after_validate(state)

    def _prepare_gate_node(self, state: WorkflowState) -> WorkflowState:
        spec = state.get("draft_spec")
        if spec is None:
            state["status"] = "error"
            state["error"] = "No draft spec available for gate preparation."
            return state
        summary = self.gate_builder.build(spec)
        state["gate_summary_lines"] = summary.to_lines()
        state["status"] = "gate_prepared"
        return state

    def _await_gate_confirmation_node(self, state: WorkflowState) -> WorkflowState:
        state["status"] = "awaiting_gate_confirmation"
        return state

    def _route_after_gate_wait(self, state: WorkflowState) -> str:
        if state.get("target_phase") in {"render", "deliver"} and state.get("gate_confirmed"):
            return "ensure_proto"
        return "end"

    def _apply_gate_confirmation_node(self, state: WorkflowState) -> WorkflowState:
        interaction = state.get("interaction") or {}
        confirmed = bool(interaction.get("confirmed", False))
        state["gate_confirmed"] = confirmed
        state["interaction"] = None
        state["status"] = "gate_confirmed" if confirmed else "awaiting_gate_confirmation"
        return state

    def _route_after_apply_gate_confirmation(self, state: WorkflowState) -> str:
        if state.get("gate_confirmed") and state.get("target_phase") in {"render", "deliver"}:
            return "ensure_proto"
        return "end"

    def _ensure_proto_node(self, state: WorkflowState) -> WorkflowState:
        spec = state.get("draft_spec")
        if spec is None:
            state["status"] = "error"
            state["error"] = "No draft spec available for proto validation."
            return state

        result = self.validator.validate(spec, require_proto=True)
        proto_issues = [issue for issue in result.issues if issue.field == "service.proto_file"]
        if proto_issues:
            state["proto_summary_lines"] = [
                "Formal tRPC generation requires a user-provided .proto contract.",
                proto_issues[0].message,
                "Provide an absolute path or a project-relative path to the .proto file, then resume the workflow.",
            ]
            state["status"] = "awaiting_proto"
            state["error"] = None
            return state

        assert spec.service.proto_file is not None
        proto_path = Path(spec.service.proto_file).expanduser()
        if not proto_path.is_absolute():
            proto_path = Path.cwd() / proto_path
        if not proto_path.exists():
            state["proto_summary_lines"] = [
                f"The .proto file was not found: {proto_path}",
                "Formal tRPC generation cannot continue until the contract file exists and is readable.",
            ]
            state["status"] = "awaiting_proto"
            state["error"] = None
            return state

        try:
            self.renderer.inspect_contract(spec)
        except ProtoContractError as exc:
            state["proto_summary_lines"] = [
                f"The provided .proto file could not be used: {exc}",
                "Please provide a valid .proto file that contains a service definition and at least one rpc method.",
            ]
            state["status"] = "awaiting_proto"
            state["error"] = None
            return state

        state["proto_summary_lines"] = [
            f"Using contract: {proto_path}",
            "Formal tRPC generation can now continue with the user-provided protocol.",
        ]
        state["status"] = "proto_ready"
        state["error"] = None
        return state

    def _route_after_ensure_proto(self, state: WorkflowState) -> str:
        if state.get("status") == "proto_ready":
            return "render_project"
        return "await_proto"

    def _await_proto_node(self, state: WorkflowState) -> WorkflowState:
        state["status"] = "awaiting_proto"
        state["interaction"] = None
        return state

    def _apply_proto_submission_node(self, state: WorkflowState) -> WorkflowState:
        spec = state.get("draft_spec")
        interaction = state.get("interaction") or {}
        proto_file = str(interaction.get("proto_file") or "").strip()
        if spec is None:
            state["status"] = "error"
            state["error"] = "No draft spec available for proto updates."
            return state
        state["draft_spec"] = apply_field_updates(spec, {"service.proto_file": proto_file})
        state["interaction"] = None
        state["status"] = "proto_submitted"
        return state

    def _render_project_node(self, state: WorkflowState) -> WorkflowState:
        spec = state.get("draft_spec")
        if spec is None:
            state["status"] = "error"
            state["error"] = "No draft spec available for rendering."
            return state
        try:
            rendered = self.renderer.render_tree(spec)
        except ProtoContractError as exc:
            state["proto_summary_lines"] = [
                f"The provided .proto file could not be rendered: {exc}",
                "Update service.proto_file and resume the workflow.",
            ]
            state["status"] = "awaiting_proto"
            state["error"] = None
            return state
        state["rendered_files"] = rendered
        state["verification_attempts"] = 0
        state["build_feedback"] = None
        output_dir = state.get("output_dir")
        if output_dir:
            self.renderer.write_tree(rendered, Path(output_dir))
        state["status"] = "rendered"
        state["error"] = None
        return state

    def _refine_code_node(self, state: WorkflowState) -> WorkflowState:
        spec = state.get("draft_spec")
        if spec is None:
            state["status"] = "error"
            state["error"] = "No draft spec available for code refinement."
            return state
        session = MainAgentSessionState(
            user_request=state.get("user_request", ""),
            draft_spec=spec,
            additional_context=list(state.get("additional_context", [])),
            clarification_history=[ClarificationTurn(**turn) for turn in state.get("clarification_history", [])],
            rendered_files=dict(state.get("rendered_files", {})),
        )
        try:
            result = CodeRefinerAgent(model=state.get("model"), provider=self.provider).refine_session(session)
        except CodeRefinerError as exc:
            state["status"] = "error"
            state["error"] = str(exc)
            return state

        state["rendered_files"] = result.files
        state["refinement_notes"] = result.notes
        output_dir = state.get("output_dir")
        if output_dir:
            self.renderer.write_tree(result.files, Path(output_dir))
        state["status"] = "refined"
        state["error"] = None
        return state

    def _verify_build_node(self, state: WorkflowState) -> WorkflowState:
        rendered_files = state.get("rendered_files", {})
        if not rendered_files:
            state["status"] = "error"
            state["error"] = "No rendered files available for build verification."
            return state

        result = self.verifier.verify(rendered_files)
        state["verification_summary_lines"] = result.summary_lines
        state["build_feedback"] = None if result.success else result.feedback
        if result.success:
            state["status"] = "verified"
            state["error"] = None
            return state

        if "not found in PATH" in result.feedback:
            state["status"] = "error"
            state["error"] = result.feedback
            return state

        attempts = int(state.get("verification_attempts", 0)) + 1
        state["verification_attempts"] = attempts
        if attempts > MAX_BUILD_REPAIR_ATTEMPTS:
            state["status"] = "error"
            state["error"] = (
                f"Build verification failed after {MAX_BUILD_REPAIR_ATTEMPTS} automatic repair attempts.\n\n"
                f"{result.feedback}"
            )
            return state

        state["status"] = "build_verification_failed"
        state["error"] = None
        return state

    def _route_after_verify_build(self, state: WorkflowState) -> str:
        if state.get("status") == "verified":
            if state.get("target_phase") == "deliver":
                return "prepare_github_delivery"
            return "end"
        if state.get("status") == "build_verification_failed":
            return "repair_build_errors"
        return "end"

    def _repair_build_errors_node(self, state: WorkflowState) -> WorkflowState:
        spec = state.get("draft_spec")
        if spec is None:
            state["status"] = "error"
            state["error"] = "No draft spec available for build-error repair."
            return state

        repair_context = list(state.get("additional_context", []))
        feedback = state.get("build_feedback")
        if feedback:
            repair_context.append(feedback)

        session = MainAgentSessionState(
            user_request=state.get("user_request", ""),
            draft_spec=spec,
            additional_context=repair_context,
            clarification_history=[ClarificationTurn(**turn) for turn in state.get("clarification_history", [])],
            rendered_files=dict(state.get("rendered_files", {})),
        )
        try:
            result = CodeRefinerAgent(model=state.get("model"), provider=self.provider).refine_session(session)
        except CodeRefinerError as exc:
            state["status"] = "error"
            state["error"] = str(exc)
            return state

        notes = list(result.notes)
        notes.append("Applied build verification feedback and retried local Go verification.")
        state["rendered_files"] = result.files
        state["refinement_notes"] = notes
        output_dir = state.get("output_dir")
        if output_dir:
            self.renderer.write_tree(result.files, Path(output_dir))
        state["status"] = "repaired_from_build_feedback"
        state["error"] = None
        return state

    def _prepare_github_delivery_node(self, state: WorkflowState) -> WorkflowState:
        spec = state.get("draft_spec")
        repo_owner = spec.repo.owner if spec is not None else None
        repo_name = spec.repo.name if spec is not None else None
        full_name = "/".join(part for part in [repo_owner, repo_name] if part)
        lines = [
            "GitHub delivery will upload the refined and build-verified project using GITHUB_TOKEN.",
            f"Target repository: {full_name or 'not set yet'}",
            "The workflow can create the repository first, then push one generated commit.",
        ]
        state["github_summary_lines"] = lines
        state["status"] = "awaiting_github_delivery"
        state["interaction"] = None
        state["error"] = None
        return state

    def _await_github_delivery_node(self, state: WorkflowState) -> WorkflowState:
        state["status"] = "awaiting_github_delivery"
        return state

    def _apply_github_delivery_node(self, state: WorkflowState) -> WorkflowState:
        interaction = state.get("interaction") or {}
        payload = dict(interaction.get("payload", {}))
        state["github_delivery"] = payload
        state["interaction"] = None
        state["status"] = "github_delivery_configured"
        return state

    def _deliver_to_github_node(self, state: WorkflowState) -> WorkflowState:
        spec = state.get("draft_spec")
        rendered_files = state.get("rendered_files", {})
        payload = state.get("github_delivery", {})
        if spec is None:
            state["status"] = "error"
            state["error"] = "No draft spec available for GitHub delivery."
            return state
        if not rendered_files:
            state["status"] = "error"
            state["error"] = "No rendered files available for GitHub delivery."
            return state

        owner = str(payload.get("owner") or spec.repo.owner or "").strip()
        repo = str(payload.get("repo") or spec.repo.name or "").strip()
        if not owner or not repo:
            state["status"] = "error"
            state["error"] = "GitHub delivery requires both repo.owner and repo.name."
            return state

        repository_full_name = f"{owner}/{repo}"
        create_repo = bool(payload.get("create_repo", True))
        commit_message = str(payload.get("commit_message") or "Add generated NL2Service scaffold")

        try:
            created_repo = False
            repository_url = f"https://github.com/{repository_full_name}"
            if create_repo:
                repository_url = self.github_provider.create_repo(owner, repo)
                created_repo = True
            result = self.github_provider.commit_files(repository_full_name, rendered_files, message=commit_message)
            state["github_delivery"] = {
                "owner": owner,
                "repo": repo,
                "repository_full_name": repository_full_name,
                "repository_url": result.repository_url or repository_url,
                "branch": result.branch,
                "commit_sha": result.commit_sha,
                "create_repo": create_repo,
                "created_repo": created_repo,
                "commit_message": commit_message,
            }
            state["status"] = "delivered"
            state["error"] = None
            return state
        except GitHubAPIError as exc:
            state["status"] = "error"
            state["error"] = str(exc)
            return state
