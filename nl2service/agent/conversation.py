from __future__ import annotations

import os
import json
import re
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field
import yaml

from nl2service.agent.provider import LLMProvider
from nl2service.spec.models import ServiceSpec
from nl2service.workflow.updates import apply_field_updates


class ClarificationValue(BaseModel):
    value: Any


class ConversationUpdate(BaseModel):
    field: str
    value_json: str


class ConversationDecision(BaseModel):
    intent: Literal["answer", "correct", "question", "cancel"]
    answer_json: str | None = None
    updates: list[ConversationUpdate] = Field(default_factory=list)
    response: str | None = None


class ClarificationInterpreter:
    def __init__(self, provider: LLMProvider, model: str | None = None) -> None:
        self.provider = provider
        self.model = model or os.getenv("NL2SERVICE_OPENAI_MODEL") or "gpt-4.1-mini"

    def interpret(self, field: str, question: str, answer: str) -> Any:
        try:
            llm = self.provider.get_model(self.model).with_structured_output(
                ClarificationValue,
                method="function_calling",
            )
            result = llm.invoke(
                [
                    SystemMessage(
                        content=(
                            "Interpret every natural-language clarification answer as the JSON-compatible value "
                            "for the exact ServiceSpec field. Use the question as context. Preserve identifiers "
                            "and paths, normalize enum meaning and casing, do not invent information, and treat "
                            "explicit absence such as 'none' as null. Lists must be JSON arrays, booleans must be "
                            "true/false, ports and replicas must be numbers, and endpoints must be objects with "
                            "path and method."
                        )
                    ),
                    HumanMessage(content=f"Field: {field}\nQuestion: {question}\nUser answer: {answer}"),
                ]
            )
            interpreted = result.value
        except Exception:
            parsed = yaml.safe_load(answer)
            interpreted = answer.strip() if parsed is None else parsed
        return self._normalize(field, interpreted, answer)

    def route_turn(
        self,
        pending: dict[str, Any],
        answer: str,
        spec: Any,
        conversation_context: dict[str, Any] | None = None,
    ) -> ConversationDecision:
        model = self.provider.get_model(self.model).with_structured_output(
            ConversationDecision,
            method="function_calling",
        )
        decision = self._invoke_validated(model,
            [
                SystemMessage(
                    content=(
                        "You are routing one turn in an ongoing service-design conversation. The user is not "
                        "filling out a rigid form. Classify their intent as: answer (answering the pending "
                        "question), correct (changing any current or previous specification field), question "
                        "(asking for an explanation without changing state), or cancel. For answer, put the "
                        "JSON-encoded value in answer_json. For corrections, emit every changed dotted "
                        "ServiceSpec field in updates, with each value JSON-encoded in value_json. Use response "
                        "to answer user questions clearly. Never invent credentials or infrastructure. Do not "
                        "store conversational references like 'that one' or 'that's the project name' as literal "
                        "infrastructure values; resolve them from the current spec or ask for the exact value. "
                        "List indices must already exist in the current spec. To add an input field or rule, "
                        "replace its entire containing list, preserving existing entries; never use an out-of-range index."
                    )
                ),
                HumanMessage(
                    content=(
                        f"Pending clarification: {json.dumps(pending, default=str)}\n"
                        f"ServiceSpec JSON Schema: {json.dumps(ServiceSpec.model_json_schema())}\n"
                        f"Current spec: {json.dumps(spec.model_dump(mode='json', exclude_none=True) if spec else {}, default=str)}\n"
                        f"Conversation context: {json.dumps(conversation_context or {}, default=str)}\n"
                        f"User message: {answer}"
                    )
                ),
            ], spec
        )
        return decision

    def route_confirmation(
        self,
        pending: dict[str, Any],
        answer: str,
        spec: Any,
        conversation_context: dict[str, Any] | None = None,
    ) -> ConversationDecision:
        model = self.provider.get_model(self.model).with_structured_output(
            ConversationDecision,
            method="function_calling",
        )
        return self._invoke_validated(model,
            [
                SystemMessage(
                    content=(
                        "Route one message at an approval gate. Determine whether the user is approving, "
                        "rejecting/cancelling, correcting the specification, or asking a question before deciding. "
                        "For a correction such as 'database port - 3301', use intent=correct and emit dotted "
                        "ServiceSpec field updates such as database.port with JSON-encoded values. Use intent=answer with "
                        "answer_json=true or false only for an unambiguous decision. Use intent=question and "
                        "response to answer questions from the supplied specification and approval details. "
                        "Never interpret a question as approval. Never store conversational references such as "
                        "'that one' or 'that's the project name' as infrastructure identifiers; resolve them from "
                        "the current spec or ask for the literal value. "
                        "Only use list indices already present in the spec. To add fields or rules, replace "
                        "the complete containing list and preserve its existing entries. Never emit out-of-range indices."
                    )
                ),
                HumanMessage(
                    content=(
                        f"Approval details: {json.dumps(pending, default=str)}\n"
                        f"ServiceSpec JSON Schema: {json.dumps(ServiceSpec.model_json_schema())}\n"
                        f"Current spec: {json.dumps(spec.model_dump(mode='json', exclude_none=True) if spec else {}, default=str)}\n"
                        f"Conversation context: {json.dumps(conversation_context or {}, default=str)}\n"
                        f"User message: {answer}"
                    )
                ),
            ], spec
        )

    def _invoke_validated(self, model: Any, messages: list[Any], spec: Any) -> ConversationDecision:
        decision = model.invoke(messages)
        # Repair malformed model corrections once using only the public schema
        # and validation diagnostics. No user state changes until all updates pass.
        for attempt in range(2):
            if decision.intent != "correct" or spec is None:
                return decision
            try:
                updates = {
                    item.field: self._normalize(item.field, json.loads(item.value_json))
                    for item in decision.updates
                }
                apply_field_updates(spec, updates)
                return decision
            except (ValueError, TypeError, AttributeError) as exc:
                if attempt:
                    return decision  # Runtime retains the gate and reports failure.
                repaired = model.invoke([*messages, HumanMessage(content=(
                    "Your proposed correction failed validation. Return a corrected decision for the "
                    "same user message; preserve its meaning and all existing unrelated fields. "
                    "Follow the supplied ServiceSpec schema exactly. operations is a coarse enum: "
                    "use other for checks not covered by its arithmetic/conditional values, and retain "
                    "the full validation and integer arithmetic requirements in expression text. "
                    "Do not change intent to approval or discard the correction to avoid validation.\n"
                    f"Invalid decision: {decision.model_dump_json()}\nValidation: {exc}"
                ))])
                if repaired.intent != "correct":
                    return decision
                decision = repaired
        return decision

    @staticmethod
    def _normalize(field: str, value: Any, source: str | None = None) -> Any:
        if field.endswith(("request_description", "response_description", "schema_description")):
            return str(source or value or "").strip()
        opaque_fields = {
            "service.module",
            "repo.owner",
            "repo.name",
            "deploy.namespace",
            "deploy.gcp_project",
            "deploy.cluster",
            "deploy.location",
            "kafka.topic",
            "kafka.group",
            "kafka.ca_file",
            "kafka.secret_name",
            "database.host",
            "database.database",
            "database.secret_name",
        }
        source_value = str(source or "").strip()
        if field == "kafka.brokers" and source_value and not re.search(r"\s", source_value):
            return [part for part in source_value.split(",") if part]
        if field in opaque_fields and source_value and not re.search(r"\s", source_value):
            return source_value
        normalized_answer = str(value or "").strip().lower()
        if field == "deploy.platform":
            aliases = {
                "gke": "gke",
                "google kubernetes engine": "gke",
                "google cloud": "gke",
                "generic": "generic",
                "generic kubernetes": "generic",
                "kubernetes": "generic",
                "k8s": "generic",
            }
            return aliases.get(normalized_answer, normalized_answer)
        if field == "database.type":
            aliases = {
                "mysql": "mysql",
                "my sql": "mysql",
                "postgres": "postgres",
                "postgresql": "postgres",
            }
            return aliases.get(normalized_answer, normalized_answer)
        if field == "service.name":
            value = str(value or "").strip()
            value = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", value)
            value = re.sub(r"[^A-Za-z0-9]+", "-", value)
            return value.strip("-").lower()
        return value
