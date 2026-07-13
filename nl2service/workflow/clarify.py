from __future__ import annotations

from dataclasses import dataclass, field

from nl2service.spec.models import ServiceSpec
from nl2service.spec.validator import ServiceSpecValidator, ValidationIssue


@dataclass(slots=True)
class ClarificationItem:
    field: str
    question: str
    reason: str
    severity: str = "error"


@dataclass(slots=True)
class ClarificationSession:
    spec: ServiceSpec
    items: list[ClarificationItem] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return not self.items


class ClarificationSessionBuilder:
    def __init__(self, validator: ServiceSpecValidator | None = None) -> None:
        self.validator = validator or ServiceSpecValidator()

    def build(self, spec: ServiceSpec) -> ClarificationSession:
        result = self.validator.validate(spec)
        items: list[ClarificationItem] = []
        for issue in result.issues:
            question = self.validator.question_for_field(issue.field)
            if not question:
                continue
            items.append(self._to_item(issue, question))
        return ClarificationSession(spec=spec, items=items)

    def _to_item(self, issue: ValidationIssue, question: str) -> ClarificationItem:
        return ClarificationItem(
            field=issue.field,
            question=question,
            reason=issue.message,
            severity=issue.severity,
        )
