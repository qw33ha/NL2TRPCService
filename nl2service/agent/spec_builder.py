from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from nl2service.agent.provider import LLMProvider
from nl2service.agent.prompts import SPEC_BUILDER_SYSTEM_PROMPT
from nl2service.agent.session import SpecBuilderSessionState
from nl2service.spec.models import ServiceSpec
from nl2service.spec.normalize import ServiceSpecNormalizer

DEFAULT_SPEC_BUILDER_MODEL = "gpt-4.1-mini"


class SpecBuilderError(RuntimeError):
    """Raised when the LLM-backed spec builder cannot produce a draft."""


@dataclass(slots=True)
class DraftBuildResult:
    spec: ServiceSpec
    extracted_fields: list[str]
    notes: list[str]
    model: str


@dataclass(slots=True)
class SpecBuilderAgent:
    """LangChain-backed NL -> ServiceSpec draft builder."""

    system_prompt: str = SPEC_BUILDER_SYSTEM_PROMPT
    model: str | None = None
    provider: LLMProvider | None = None
    normalizer: ServiceSpecNormalizer | None = None

    def build_from_text(self, text: str) -> DraftBuildResult:
        session = SpecBuilderSessionState(user_request=text.strip())
        return self.build_from_session(session)

    def build_from_session(self, session: SpecBuilderSessionState) -> DraftBuildResult:
        if not session.user_request.strip():
            raise SpecBuilderError("The natural-language request is empty.")

        model_name = self.model or os.getenv("NL2SERVICE_OPENAI_MODEL") or DEFAULT_SPEC_BUILDER_MODEL
        provider = self.provider or LLMProvider()
        try:
            llm = provider.get_model(model_name).with_structured_output(ServiceSpec)
        except RuntimeError as exc:
            raise SpecBuilderError(str(exc)) from exc

        parsed = llm.invoke(self._build_messages(session))
        if parsed is None:
            raise SpecBuilderError("The model did not return a structured ServiceSpec draft.")

        spec = self._coerce_spec(parsed)
        spec = (self.normalizer or ServiceSpecNormalizer()).normalize(spec)
        return DraftBuildResult(
            spec=spec,
            extracted_fields=self._collect_extracted_fields(spec),
            notes=self._build_notes(spec),
            model=model_name,
        )

    def _build_messages(self, session: SpecBuilderSessionState) -> list[Any]:
        user_sections = [f"Current user request:\n{session.user_request.strip()}"]
        if session.draft_spec is not None:
            draft = session.draft_spec.model_dump(mode="json", exclude_none=True)
            user_sections.append(f"Current draft spec:\n{draft}")
        if session.additional_context:
            user_sections.append("Additional context:\n" + "\n".join(f"- {item}" for item in session.additional_context))
        if session.clarification_history:
            history = "\n".join(
                f"Q: {turn.question}\nA: {turn.answer}" for turn in session.clarification_history
            )
            user_sections.append(f"Clarification history:\n{history}")

        return [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content="\n\n".join(user_sections)),
        ]

    def _coerce_spec(self, parsed: Any) -> ServiceSpec:
        if isinstance(parsed, ServiceSpec):
            return parsed
        if hasattr(parsed, "model_dump"):
            return ServiceSpec.model_validate(parsed.model_dump(mode="python"))
        if isinstance(parsed, dict):
            return ServiceSpec.model_validate(parsed)
        raise SpecBuilderError(f"Unsupported parsed response type: {type(parsed).__name__}")

    def _collect_extracted_fields(self, spec: ServiceSpec) -> list[str]:
        baseline = ServiceSpec().model_dump(mode="python")
        current = spec.model_dump(mode="python")
        fields: list[str] = []
        self._walk_changes(current=current, baseline=baseline, prefix="", fields=fields)
        return fields

    def _walk_changes(self, current: Any, baseline: Any, prefix: str, fields: list[str]) -> None:
        if isinstance(current, dict):
            for key, value in current.items():
                next_prefix = f"{prefix}.{key}" if prefix else key
                base_value = baseline.get(key) if isinstance(baseline, dict) else None
                self._walk_changes(value, base_value, next_prefix, fields)
            return

        if isinstance(current, list):
            if current and current != baseline:
                fields.append(prefix)
            return

        if current in (None, "", {}, []):
            return
        if current != baseline:
            fields.append(prefix)

    def _build_notes(self, spec: ServiceSpec) -> list[str]:
        notes = [
            "This draft was produced by an LLM and still needs validation, clarification, and gate approval.",
            "Platform defaults and policy constraints were re-applied after model generation.",
        ]
        if spec.kafka.enabled and not spec.kafka.secret_name:
            notes.append("Kafka credentials were intentionally left blank and must come from a Kubernetes Secret reference.")
        if spec.database.enabled and not spec.database.secret_name:
            notes.append("Database credentials were intentionally left blank and must come from a Kubernetes Secret reference.")
        if spec.exposure.type == "loadBalancer" and not spec.policy.allow_load_balancer:
            notes.append("LoadBalancer was requested, but policy approval still needs to be confirmed before execution.")
        return notes
