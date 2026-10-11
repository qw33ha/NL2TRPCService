from __future__ import annotations

from dataclasses import dataclass
import os
import re
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
        # The simple HTTP skeleton owns server startup and route registration.
        # Model changes belong in handler bodies; replacing the framework router
        # can compile while silently serving 404 for every endpoint.
        spec = session.draft_spec
        preserved = False
        if spec and spec.service.enable_http and not spec.service.enable_trpc and not spec.database.enabled and not spec.kafka.enabled:
            if "main.go" in session.rendered_files:
                preserved = files.get("main.go") != session.rendered_files["main.go"]
                files["main.go"] = session.rendered_files["main.go"]
            path = "handler/http_handler.go"
            original = session.rendered_files.get(path, "")
            refined = files.get(path, "")
            source_span = self._register_span(original)
            target_span = self._register_span(refined)
            if source_span and target_span:
                registration = original[source_span[0]:source_span[1]]
                if refined[target_span[0]:target_span[1]] != registration:
                    refined = refined[:target_span[0]] + registration + refined[target_span[1]:]
                    if 'thttp "trpc.group/trpc-go/trpc-go/http"' not in refined:
                        if "import (" in refined:
                            refined = refined.replace("import (", 'import (\n\tthttp "trpc.group/trpc-go/trpc-go/http"', 1)
                        else:
                            refined = re.sub(r"(package\s+\w+)", r'\1\nimport thttp "trpc.group/trpc-go/trpc-go/http"', refined, count=1)
                    files[path] = refined
                    preserved = True
        if not files:
            raise MainAgentError("The model did not return any refined files.")
        notes = [note.strip() for note in parsed.summary if note and note.strip()]
        if not notes:
            notes = ["Rendered scaffold was passed through the main LLM agent for code refinement."]
        if preserved:
            notes.append("Preserved the deterministic HTTP server lifecycle and framework route registrations.")
        return RefinementResult(files=files, notes=notes, model=model_name)

    @staticmethod
    def _register_span(source: str) -> tuple[int, int] | None:
        masked = re.sub(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|`[^`]*`|\'(?:\\.|[^\'\\])*\'',
                        lambda match: " " * len(match.group()), source)
        match = re.search(r"func \([^)]*\*HTTPHandler\) Register\(\)\s*\{", masked)
        if not match:
            return None
        depth = 1
        for index in range(match.end(), len(source)):
            if masked[index] == "{":
                depth += 1
            elif masked[index] == "}":
                depth -= 1
                if depth == 0:
                    return match.start(), index + 1
        return None

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
