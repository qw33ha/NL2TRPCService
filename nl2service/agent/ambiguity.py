from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from nl2service.agent.provider import LLMProvider
from nl2service.spec.models import ServiceSpec


class AmbiguityItem(BaseModel):
    key: str
    field: str | None = None
    question: str
    reason: str
    impact: Literal["behavior", "security", "cost", "deployment"]
    priority: Literal["blocking", "important", "optional"]


class AmbiguityReview(BaseModel):
    items: list[AmbiguityItem] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


@dataclass(slots=True)
class AmbiguityAnalyzer:
    provider: LLMProvider
    model: str | None = None

    def analyze(
        self,
        request: str,
        spec: ServiceSpec,
        history: list[dict[str, str]],
        resolved: list[str],
    ) -> AmbiguityReview:
        model_name = self.model or os.getenv("NL2SERVICE_OPENAI_MODEL") or "gpt-4.1-mini"
        llm = self.provider.get_model(model_name).with_structured_output(
            AmbiguityReview,
            method="function_calling",
        )
        review = llm.invoke(
            [
                SystemMessage(
                    content=(
                        "Review a service specification for material ambiguity that deterministic schema validation "
                        "cannot detect. Ask only questions whose answers affect behavior, security, cost, or deployment. "
                        "Use blocking for required behavioral choices, important for consequential uncertainty, and "
                        "optional for safe assumptions that can be shown at approval. Give each ambiguity a stable key "
                        "based on the unresolved decision and reason. The optional field may name a real scalar dotted "
                        "ServiceSpec field only when the answer directly changes that field. Leave field null for open-ended "
                        "behavioral requirements, schema details, business rules, explanations, and other information that "
                        "belongs in conversational context rather than the structured generation spec. Do not repeat "
                        "resolved keys or questions already answered in history. Return at most five items. Do not turn "
                        "minor implementation preferences into questions. Do not ask users to define internal platform "
                        "policy fields such as policy.require_gate. Treat one replica and framework defaults as optional "
                        "unless the user raised scaling. Avoid duplicate questions about the same behavior. List fields "
                        "may use numeric dotted indices such as endpoints.0.request_description. Never target a whole "
                        "object or list such as database, kafka, deploy, service, or endpoints."
                    )
                ),
                HumanMessage(
                    content=(
                        f"Original request:\n{request}\n\n"
                        f"Current spec:\n{spec.model_dump_json(exclude_none=True)}\n\n"
                        f"Clarification history:\n{history[-20:]}\n\n"
                        f"Resolved ambiguity keys:\n{resolved}"
                    )
                ),
            ]
        )
        review.items = [
            item for item in review.items
            if item.field is None or self._is_scalar_field(spec, item.field)
        ]
        return review

    @staticmethod
    def _is_scalar_field(spec: ServiceSpec, field: str) -> bool:
        cursor: object = spec.model_dump(mode="python")
        try:
            for part in field.split("."):
                if isinstance(cursor, list):
                    cursor = cursor[int(part)]
                elif isinstance(cursor, dict):
                    cursor = cursor[part]
                else:
                    return False
        except (KeyError, IndexError, TypeError, ValueError):
            return False
        return not isinstance(cursor, (dict, list))
