from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Literal, TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from nl2service.agent.prompts import CODE_REFINER_SYSTEM_PROMPT, SPEC_BUILDER_SYSTEM_PROMPT
from nl2service.agent.provider import LLMProvider
from nl2service.agent.session import MainAgentSessionState
from nl2service.spec.models import ServiceSpec
from nl2service.spec.normalize import ServiceSpecNormalizer

DEFAULT_MAIN_AGENT_MODEL = "gpt-4.1-mini"


class MainAgentError(RuntimeError):
    """Raised when the unified main agent cannot complete the requested action."""


class RefinedRender(BaseModel):
    files: dict[str, str] = Field(default_factory=dict)
    summary: list[str] = Field(default_factory=list)


@dataclass(slots=True)
class DraftBuildResult:
    spec: ServiceSpec
    extracted_fields: list[str]
    notes: list[str]
    model: str


@dataclass(slots=True)
class RefinementResult:
    files: dict[str, str]
    notes: list[str]
    model: str


MainAgentAction = Literal["draft_spec", "refine_code", "repair_code"]
StructuredOutputT = TypeVar("StructuredOutputT")


@dataclass(slots=True)
class MainLLMAgent:
    """Unified main-agent entry point for draft/refine/repair LLM work."""

    model: str | None = None
    provider: LLMProvider | None = None
    normalizer: ServiceSpecNormalizer | None = None

    def draft_spec(self, session: MainAgentSessionState) -> DraftBuildResult:
        if not session.user_request.strip():
            raise MainAgentError("The natural-language request is empty.")
        model_name, parsed = self._invoke_structured(
            action="draft_spec",
            schema=ServiceSpec,
            messages=self._build_spec_messages(session),
        )
        spec = self._coerce_spec(parsed)
        spec = (self.normalizer or ServiceSpecNormalizer()).normalize(spec)
        return DraftBuildResult(
            spec=spec,
            extracted_fields=self._collect_extracted_fields(spec),
            notes=self._build_notes(spec),
            model=model_name,
        )

    def refine_code(self, session: MainAgentSessionState) -> RefinementResult:
        if not session.rendered_files:
            raise MainAgentError("There are no rendered files to refine.")
        model_name, parsed = self._invoke_structured(
            action="repair_code" if session.repair_feedback else "refine_code",
            schema=RefinedRender,
            messages=self._build_refine_messages(session),
        )
        files = dict(session.rendered_files)
        files.update(parsed.files)
        if not files:
            raise MainAgentError("The model did not return any refined files.")
        notes = [note.strip() for note in parsed.summary if note and note.strip()]
        if not notes:
            notes = ["Rendered scaffold was passed through the main LLM agent for code refinement."]
        return RefinementResult(files=files, notes=notes, model=model_name)

    def _invoke_structured(
        self,
        *,
        action: MainAgentAction,
        schema: type[StructuredOutputT],
        messages: list[Any],
    ) -> tuple[str, StructuredOutputT]:
        model_name = self.model or os.getenv("NL2SERVICE_OPENAI_MODEL") or DEFAULT_MAIN_AGENT_MODEL
        provider = self.provider or LLMProvider()
        try:
            llm = provider.get_model(model_name).with_structured_output(
                schema,
                method="function_calling",
            )
        except RuntimeError as exc:
            raise MainAgentError(str(exc)) from exc
        try:
            parsed = llm.invoke(messages)
        except Exception as exc:
            raise MainAgentError(f"Main agent action '{action}' failed: {exc}") from exc
        if parsed is None:
            raise MainAgentError(f"Main agent action '{action}' returned no structured result.")
        return model_name, parsed

    @staticmethod
    def _build_spec_messages(session: MainAgentSessionState) -> list[Any]:
        user_sections = [f"Current user request:\n{session.user_request.strip()}"]
        if session.draft_spec is not None:
            draft = session.draft_spec.model_dump(mode="json", exclude_none=True)
            user_sections.append(f"Current draft spec:\n{draft}")
        if session.additional_context:
            user_sections.append(
                "Additional context:\n" + "\n".join(f"- {item}" for item in session.additional_context)
            )
        if session.clarification_history:
            history = "\n".join(
                f"Q: {turn.question}\nA: {turn.answer}" for turn in session.clarification_history
            )
            user_sections.append(f"Clarification history:\n{history}")
        return [
            SystemMessage(content=SPEC_BUILDER_SYSTEM_PROMPT),
            HumanMessage(content="\n\n".join(user_sections)),
        ]

    @staticmethod
    def _build_refine_messages(session: MainAgentSessionState) -> list[Any]:
        sections = [f"Original user request:\n{session.user_request.strip()}"]
        if session.draft_spec is not None:
            sections.append(
                "Final structured spec:\n"
                + str(session.draft_spec.model_dump(mode="json", exclude_none=True))
            )
        if session.additional_context:
            sections.append(
                "Additional context:\n" + "\n".join(f"- {item}" for item in session.additional_context)
            )
        if session.repair_feedback:
            sections.append(
                "REQUIRED REPAIR FEEDBACK FROM VERIFICATION/CI:\n"
                + session.repair_feedback
                + "\n\nFix the reported failure directly. Do not return unchanged files."
            )
        if session.clarification_history:
            history = "\n".join(
                f"Q: {turn.question}\nA: {turn.answer}" for turn in session.clarification_history
            )
            sections.append(f"Clarification history:\n{history}")
        if session.reference_files:
            reference_blocks = [
                f"REFERENCE FILE: {path}\n```\n{content}\n```"
                for path, content in session.reference_files.items()
            ]
            sections.append(
                "Selected verified examples. Adapt their public framework patterns, but do not copy "
                "credentials, provider endpoints, module names, or unrelated behavior:\n"
                + "\n\n".join(reference_blocks)
            )
        rendered_blocks = [
            f"FILE: {path}\n```\n{content}\n```"
            for path, content in session.rendered_files.items()
        ]
        sections.append("Rendered scaffold files:\n" + "\n\n".join(rendered_blocks))
        return [
            SystemMessage(content=CODE_REFINER_SYSTEM_PROMPT),
            HumanMessage(content="\n\n".join(sections)),
        ]

    @staticmethod
    def _coerce_spec(parsed: Any) -> ServiceSpec:
        if isinstance(parsed, ServiceSpec):
            return parsed
        if hasattr(parsed, "model_dump"):
            return ServiceSpec.model_validate(parsed.model_dump(mode="python"))
        if isinstance(parsed, dict):
            return ServiceSpec.model_validate(parsed)
        raise MainAgentError(f"Unsupported parsed response type: {type(parsed).__name__}")

    @staticmethod
    def _collect_extracted_fields(spec: ServiceSpec) -> list[str]:
        baseline = ServiceSpec().model_dump(mode="python")
        current = spec.model_dump(mode="python")
        fields: list[str] = []
        MainLLMAgent._walk_changes(current=current, baseline=baseline, prefix="", fields=fields)
        return fields

    @staticmethod
    def _walk_changes(current: Any, baseline: Any, prefix: str, fields: list[str]) -> None:
        if isinstance(current, dict):
            for key, value in current.items():
                next_prefix = f"{prefix}.{key}" if prefix else key
                base_value = baseline.get(key) if isinstance(baseline, dict) else None
                MainLLMAgent._walk_changes(value, base_value, next_prefix, fields)
            return
        if isinstance(current, list):
            if current and current != baseline:
                fields.append(prefix)
            return
        if current in (None, "", {}, []):
            return
        if current != baseline:
            fields.append(prefix)

    @staticmethod
    def _build_notes(spec: ServiceSpec) -> list[str]:
        notes = [
            "This draft was produced by an LLM and still needs validation, clarification, and gate approval.",
            "Platform defaults and policy constraints were re-applied after model generation.",
        ]
        if spec.kafka.enabled and not spec.kafka.secret_name:
            notes.append(
                "Kafka credentials were intentionally left blank and must come from a Kubernetes Secret reference."
            )
        if spec.database.enabled and not spec.database.secret_name:
            notes.append(
                "Database credentials were intentionally left blank and must come from a Kubernetes Secret reference."
            )
        if spec.exposure.type == "loadBalancer" and not spec.policy.allow_load_balancer:
            notes.append(
                "LoadBalancer was requested, but policy approval still needs to be confirmed before execution."
            )
        return notes
