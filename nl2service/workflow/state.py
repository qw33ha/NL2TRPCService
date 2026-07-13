from __future__ import annotations

from typing import Any

from typing_extensions import NotRequired, TypedDict

from nl2service.spec.models import ServiceSpec


class WorkflowState(TypedDict):
    user_request: str
    model: str | None
    target_phase: str
    additional_context: list[str]
    clarification_history: list[dict[str, str]]
    notes: list[str]
    extracted_fields: list[str]
    gate_confirmed: bool
    interaction: dict[str, Any] | None
    draft_spec: NotRequired[ServiceSpec]
    validation_issues: list[dict[str, str]]
    clarification_items: list[dict[str, str]]
    gate_summary_lines: list[str]
    proto_summary_lines: list[str]
    verification_summary_lines: list[str]
    build_feedback: str | None
    verification_attempts: int
    rendered_files: dict[str, str]
    refinement_notes: list[str]
    output_dir: str | None
    github_delivery: dict[str, Any]
    github_summary_lines: list[str]
    status: str
    error: str | None



def issue_to_dict(issue: Any) -> dict[str, str]:
    return {
        "field": str(getattr(issue, "field", "")),
        "message": str(getattr(issue, "message", "")),
        "severity": str(getattr(issue, "severity", "error")),
    }



def clarification_to_dict(item: Any) -> dict[str, str]:
    return {
        "field": str(getattr(item, "field", "")),
        "question": str(getattr(item, "question", "")),
        "reason": str(getattr(item, "reason", "")),
        "severity": str(getattr(item, "severity", "error")),
    }
