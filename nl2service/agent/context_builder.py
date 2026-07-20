from __future__ import annotations

from nl2service.agent.session import ClarificationTurn, MainAgentSessionState
from nl2service.workflow.state import WorkflowState


def build_main_agent_session(
    state: WorkflowState,
    *,
    additional_context: list[str] | None = None,
    repair_feedback: str | None = None,
) -> MainAgentSessionState:
    return MainAgentSessionState(
        user_request=state.get("user_request", ""),
        draft_spec=state.get("draft_spec"),
        additional_context=list(
            additional_context if additional_context is not None else state.get("additional_context", [])
        ),
        clarification_history=[
            ClarificationTurn(**turn) for turn in state.get("clarification_history", [])
        ],
        rendered_files=dict(state.get("rendered_files", {})),
        reference_files=dict(state.get("example_reference_files", {})),
        repair_feedback=repair_feedback,
    )
