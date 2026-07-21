from __future__ import annotations

from pathlib import Path

from nl2service.agent.ambiguity import AmbiguityAnalyzer
from nl2service.agent.context_builder import build_main_agent_session
from nl2service.agent.main_agent import MainAgentError, MainLLMAgent
from nl2service.agent.provider import LLMProvider
from nl2service.build.go_repair import DeterministicGoRepair
from nl2service.build.verify import GoBuildVerifier
from nl2service.render.renderer import ProtoContractError, ServiceRenderer
from nl2service.spec.validator import ServiceSpecValidator
from nl2service.tools.github_tool import GitHubAPIError, GitHubApiProvider, GitHubProvider
from nl2service.workflow.clarify import ClarificationSessionBuilder
from nl2service.workflow.gate import GateSummaryBuilder
from nl2service.workflow.examples import ExampleSelector
from nl2service.workflow.nodes.delivery import GitHubActionsNodes
from nl2service.workflow.state import (
    WorkflowState,
    issue_to_dict,
)

MAX_REPAIR_ATTEMPTS = 3


class WorkflowCore:
    """Reusable workflow dependencies and nodes.

    The user-facing state graph is defined only by ConversationalServiceWorkflow.
    """

    def __init__(
        self,
        model: str | None = None,
        provider: LLMProvider | None = None,
        github_provider: GitHubProvider | None = None,
    ) -> None:
        self.model = model
        self.provider = provider or LLMProvider()
        self.github_provider = github_provider or GitHubApiProvider()
        self.github_actions = GitHubActionsNodes(self.github_provider, MAX_REPAIR_ATTEMPTS)
        self.validator = ServiceSpecValidator()
        self.clarifier = ClarificationSessionBuilder(self.validator)
        self.gate_builder = GateSummaryBuilder()
        self.renderer = ServiceRenderer()
        self.example_selector = ExampleSelector()
        self.ambiguity_analyzer = AmbiguityAnalyzer(self.provider, model)
        self.verifier = GoBuildVerifier()
        self.deterministic_go_repair = DeterministicGoRepair()

    def _build_spec_node(self, state: WorkflowState) -> WorkflowState:
        session = build_main_agent_session(state)
        try:
            result = MainLLMAgent(model=state.get("model"), provider=self.provider).draft_spec(session)
        except MainAgentError as exc:
            state["status"] = "error"
            state["error"] = str(exc)
            return state
        state["agent_notes"] = ["Main agent produced or updated the structured service specification."]
        state["draft_spec"] = result.spec
        state["model"] = result.model
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

    def _render_project_node(self, state: WorkflowState) -> WorkflowState:
        spec = state.get("draft_spec")
        if spec is None:
            state["status"] = "error"
            state["error"] = "No draft spec available for rendering."
            return state
        try:
            rendered = self.renderer.render_tree(spec)
        except ProtoContractError as exc:
            state["status"] = "error"
            state["error"] = f"The provided .proto file could not be rendered: {exc}"
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

    def _select_examples_node(self, state: WorkflowState) -> WorkflowState:
        spec = state.get("draft_spec")
        if spec is None:
            state["status"] = "error"
            state["error"] = "No draft spec available for example selection."
            return state
        bundle = self.example_selector.select(spec)
        state["selected_examples"] = bundle.examples
        state["example_reference_files"] = bundle.files
        state["status"] = "examples_selected"
        state["error"] = None
        return state

    def _refine_code_node(self, state: WorkflowState) -> WorkflowState:
        spec = state.get("draft_spec")
        if spec is None:
            state["status"] = "error"
            state["error"] = "No draft spec available for code refinement."
            return state
        session = build_main_agent_session(state)
        try:
            result = MainLLMAgent(model=state.get("model"), provider=self.provider).refine_code(session)
        except MainAgentError as exc:
            state["status"] = "error"
            state["error"] = str(exc)
            return state
        state["agent_notes"] = ["Main agent refined the rendered scaffold using the current spec and references."]
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
        if result.synchronized_files:
            rendered_files = result.synchronized_files
            state["rendered_files"] = rendered_files
            output_dir = state.get("output_dir")
            if output_dir:
                self.renderer.write_tree(rendered_files, Path(output_dir))
        state["verification_summary_lines"] = result.summary_lines
        state["build_feedback"] = None if result.success else result.feedback
        current_attempt = int(state.get("verification_attempts", 0))
        state["local_build"] = {
            "status": "passed" if result.success else "failed",
            "command": result.command,
            "exit_code": result.exit_code,
            "logs": result.feedback,
            "attempt": current_attempt,
        }
        if result.success:
            state["active_failure"] = None
            state["verification_attempts"] = 0
            state["status"] = "verified"
            state["error"] = None
            return state

        if "not found in PATH" in result.feedback:
            state["status"] = "error"
            state["error"] = result.feedback
            return state

        deterministic = self.deterministic_go_repair.apply(rendered_files, result.feedback)
        if deterministic.changed:
            state["rendered_files"] = deterministic.files
            state["refinement_notes"] = [
                *list(state.get("refinement_notes", [])),
                *deterministic.notes,
            ]
            output_dir = state.get("output_dir")
            if output_dir:
                self.renderer.write_tree(deterministic.files, Path(output_dir))
            state["status"] = "deterministic_repair_applied"
            state["error"] = None
            return state

        attempts = int(state.get("verification_attempts", 0)) + 1
        state["verification_attempts"] = attempts
        state["active_failure"] = {
            "source": "local_build",
            "stage": "local_build",
            "command": result.command,
            "exit_code": result.exit_code,
            "logs": result.feedback,
            "run_id": None,
            "commit_sha": None,
        }
        if attempts > MAX_REPAIR_ATTEMPTS:
            state["status"] = "error"
            state["error"] = (
                f"Build verification failed after {MAX_REPAIR_ATTEMPTS} automatic repair attempts.\n\n"
                f"{result.feedback}"
            )
            return state

        state["status"] = "build_verification_failed"
        state["error"] = None
        return state

    def _repair_build_errors_node(self, state: WorkflowState) -> WorkflowState:
        spec = state.get("draft_spec")
        if spec is None:
            state["status"] = "error"
            state["error"] = "No draft spec available for build-error repair."
            return state

        repair_context = list(state.get("additional_context", []))
        failure = state.get("active_failure")
        feedback = failure.get("logs") if failure else state.get("build_feedback")
        if feedback:
            repair_context.append(feedback)

        deterministic = self.deterministic_go_repair.apply(
            dict(state.get("rendered_files", {})),
            feedback or "",
        )
        if deterministic.changed:
            state["rendered_files"] = deterministic.files
            state["refinement_notes"] = [
                *list(state.get("refinement_notes", [])),
                *deterministic.notes,
            ]
            output_dir = state.get("output_dir")
            if output_dir:
                self.renderer.write_tree(deterministic.files, Path(output_dir))
            state["status"] = "repaired_from_build_feedback"
            state["error"] = None
            return state

        session = build_main_agent_session(
            state,
            additional_context=repair_context,
            repair_feedback=feedback,
        )
        previous_files = dict(state.get("rendered_files", {}))
        try:
            result = MainLLMAgent(model=state.get("model"), provider=self.provider).refine_code(session)
        except MainAgentError as exc:
            state["status"] = "error"
            state["error"] = str(exc)
            return state

        state["agent_notes"] = ["Main agent applied build feedback to repair generated files."]
        notes = list(result.notes)
        source = failure.get("source", "local_build") if failure else "local_build"
        stage = failure.get("stage", "local_build") if failure else "local_build"
        changed_files = sorted(
            path
            for path in set(previous_files) | set(result.files)
            if previous_files.get(path) != result.files.get(path)
        )
        if not changed_files:
            state["status"] = "error"
            state["error"] = (
                f"Automatic repair produced no file changes for {source}/{stage}.\n\n"
                f"CI feedback supplied to the LLM:\n{feedback or 'No diagnostic output was available.'}"
            )
            return state
        history = list(state.get("repair_history", []))
        history.append(
            {
                "source": source,
                "stage": stage,
                "attempt": len([item for item in history if item.get("source") == source]) + 1,
                "changed_files": changed_files,
                "feedback": feedback or "",
                "signature": failure.get("signature") if failure else None,
            }
        )
        state["repair_history"] = history
        notes.append(f"Applied {source}/{stage} feedback and retried local Go verification.")
        state["rendered_files"] = result.files
        state["refinement_notes"] = notes
        output_dir = state.get("output_dir")
        if output_dir:
            self.renderer.write_tree(result.files, Path(output_dir))
        state["status"] = "repaired_from_build_feedback"
        state["error"] = None
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
                "create_repo": False,
                "requested_create_repo": create_repo,
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
