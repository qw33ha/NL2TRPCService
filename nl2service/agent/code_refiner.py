from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from nl2service.agent.provider import LLMProvider
from nl2service.agent.prompts import CODE_REFINER_SYSTEM_PROMPT
from nl2service.agent.session import MainAgentSessionState

DEFAULT_CODE_REFINER_MODEL = "gpt-4.1-mini"


class CodeRefinerError(RuntimeError):
    """Raised when the LLM-backed code refiner cannot produce a refined file set."""


class RefinedRender(BaseModel):
    files: dict[str, str] = Field(default_factory=dict)
    summary: list[str] = Field(default_factory=list)


@dataclass(slots=True)
class RefinementResult:
    files: dict[str, str]
    notes: list[str]
    model: str


@dataclass(slots=True)
class CodeRefinerAgent:
    system_prompt: str = CODE_REFINER_SYSTEM_PROMPT
    model: str | None = None
    provider: LLMProvider | None = None

    def refine_session(self, session: MainAgentSessionState) -> RefinementResult:
        if not session.rendered_files:
            raise CodeRefinerError("There are no rendered files to refine.")

        model_name = self.model or os.getenv("NL2SERVICE_OPENAI_MODEL") or DEFAULT_CODE_REFINER_MODEL
        provider = self.provider or LLMProvider()
        try:
            llm = provider.get_model(model_name).with_structured_output(RefinedRender)
        except RuntimeError as exc:
            raise CodeRefinerError(str(exc)) from exc

        parsed = llm.invoke(self._build_messages(session))
        files = dict(session.rendered_files)
        files.update(parsed.files)
        if not files:
            raise CodeRefinerError("The model did not return any refined files.")

        notes = [note.strip() for note in parsed.summary if note and note.strip()]
        if not notes:
            notes = ["Rendered scaffold was passed through the main LLM agent for code refinement."]
        return RefinementResult(files=files, notes=notes, model=model_name)

    def _build_messages(self, session: MainAgentSessionState) -> list[Any]:
        sections = [f"Original user request:\n{session.user_request.strip()}"]
        if session.draft_spec is not None:
            sections.append(
                "Final structured spec:\n" + str(session.draft_spec.model_dump(mode="json", exclude_none=True))
            )
        if session.additional_context:
            sections.append("Additional context:\n" + "\n".join(f"- {item}" for item in session.additional_context))
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

        rendered_blocks: list[str] = []
        for path, content in session.rendered_files.items():
            rendered_blocks.append(f"FILE: {path}\n```\n{content}\n```")
        sections.append("Rendered scaffold files:\n" + "\n\n".join(rendered_blocks))

        return [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content="\n\n".join(sections)),
        ]
