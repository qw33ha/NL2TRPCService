from __future__ import annotations

from dataclasses import dataclass, field

from nl2service.spec.models import ServiceSpec


@dataclass(slots=True)
class ClarificationTurn:
    question: str
    answer: str


@dataclass(slots=True)
class MainAgentSessionState:
    user_request: str
    draft_spec: ServiceSpec | None = None
    additional_context: list[str] = field(default_factory=list)
    clarification_history: list[ClarificationTurn] = field(default_factory=list)
    rendered_files: dict[str, str] = field(default_factory=dict)
    reference_files: dict[str, str] = field(default_factory=dict)
    repair_feedback: str | None = None
