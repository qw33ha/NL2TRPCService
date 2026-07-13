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

    def add_context(self, text: str) -> None:
        if text.strip():
            self.additional_context.append(text.strip())

    def add_clarification(self, question: str, answer: str) -> None:
        if question.strip() and answer.strip():
            self.clarification_history.append(ClarificationTurn(question=question.strip(), answer=answer.strip()))

    def add_rendered_file(self, path: str, content: str) -> None:
        if path.strip() and content:
            self.rendered_files[path.strip()] = content


SpecBuilderSessionState = MainAgentSessionState
