from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, StrictBool, StrictInt, StrictFloat, StrictStr

from nl2service.agent.provider import LLMProvider
from nl2service.spec.models import ServiceSpec
from nl2service.workflow.updates import apply_field_updates
import re


class AmbiguityItem(BaseModel):
    key: str
    field: str | None = None
    question: str
    reason: str
    impact: Literal["behavior", "security", "cost", "deployment"]
    priority: Literal["blocking", "important", "optional"]


class SpecCorrection(BaseModel):
    field: str
    value: StrictBool | StrictInt | StrictFloat | StrictStr
    source_quote: str = Field(min_length=3, description="Exact literal quotation from request or user clarification that supports the correction.")


class AmbiguityReview(BaseModel):
    items: list[AmbiguityItem] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    corrections: list[SpecCorrection] = Field(default_factory=list)


def explicit_unknown_field_policy(spec: ServiceSpec, request: str, history: list[dict]) -> tuple[str, bool, str] | None:
    """Conservative literal policy binding: only a single JSON input endpoint."""
    inputs = [(index, endpoint) for index, endpoint in enumerate(spec.endpoints) if endpoint.method in {"POST", "PUT", "PATCH"}]
    if len(inputs) != 1:
        return None
    index, _ = inputs[0]
    policy = None
    for source in [request] + [str(turn.get("answer", "")) for turn in history]:
        found = []
        for match in re.finditer(r"\b(ignore|allow|reject)\s+unknown\s+(?:input\s+|JSON\s+)?fields\b", source, re.IGNORECASE):
            if re.search(r"\b(not|never|don't)\s*$", source[:match.start()], re.IGNORECASE):
                continue
            found.append((match.group(1).lower() != "reject", match.group()))
        for match in re.finditer(r"\barbitrary\s+(?:valid\s+)?JSON\b|\bno\s+additional\s+(?:schema\s+)?validation\b", source, re.IGNORECASE):
            if re.search(r"\b(no|not|never|don't|reject)\s+(?:accept\s+)?$", source[:match.start()], re.IGNORECASE):
                continue
            found.append((True, match.group()))
        if found and len({value for value, _ in found}) == 1:
            policy = (f"endpoints.{index}.allow_unknown_fields", found[-1][0], found[-1][1])
        elif found:
            policy = None
    return policy


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
                        "First read the original request and history: never ask to confirm an explicitly supplied name, module, "
                        "transport, method, range, error format, status or formula. HTTP-only on the trpc-go runtime is valid "
                        "and not a conflicting transport. Inclusive ranges A..B include both endpoints. An explicitly integer "
                        "input with noninteger rejection needs no float-coercion question. Do not invent middleware choices. "
                        "Use populated endpoint input_fields, business_rules and status fields as explicit decisions. "
                        "If the current IR contradicts an explicitly supplied fact, return a correction with the scalar field, "
                        "correct value and exact source_quote from the user request or an answer; do not ask the user to repeat it. "
                        "Corrections may cover service/repo names and module, endpoint field constraints, status codes, unknown-field "
                        "policy and business expressions. Never correct deployment, secrets, policy or enabled dependencies. "
                        "When the user explicitly says to ignore unknown input fields, allow_unknown_fields must be true for that "
                        "input endpoint. Never infer unknown-field policy for a GET endpoint with no input schema; it is irrelevant. "
                        "Only ask if a material decision is genuinely missing or contradictory; return zero items for a complete request. "
                        "RPC-only services need no HTTP endpoints; RPC methods and the proto file are checked in the dedicated "
                        "protocol-file stage. Do not ask for an unavailable proto path in this ambiguity review. "
                        "Use blocking for required behavioral choices, important for consequential uncertainty, and "
                        "optional for safe assumptions that can be shown at approval. Give each ambiguity a stable key "
                        "based on the unresolved decision and reason. The optional field may name a real scalar dotted "
                        "ServiceSpec field only when the answer directly changes that field. Leave field null for open-ended "
                        "behavioral requirements, schema details, business rules, explanations, and other information that "
                        "belongs in conversational context rather than the structured generation spec. Do not repeat "
                        "resolved keys or questions already answered in history. Answers in clarification history override "
                        "the original request: once deployment is declined, do not ask whether to deploy again. "
                        "When deployment is disabled, exposure type and Kubernetes probe configuration are irrelevant "
                        "and must not create blocking or important questions. Return at most five items. Do not turn "
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
        literal_policy = explicit_unknown_field_policy(spec, request, history)
        if literal_policy:
            field, value, quote = literal_policy
            review.corrections = [SpecCorrection(field=field, value=value, source_quote=quote),
                                  *[item for item in review.corrections if item.field != field]]
        answered_fields = {turn.get("field") for turn in history if turn.get("field")}
        review.items = [
            item for item in review.items
            if item.field not in answered_fields
            and item.field != "policy.require_gate"
            and not self._irrelevant_input_policy(spec, item.field)
            and not self._explicit_error_format(spec, item.field, request)
            and not (literal_policy and item.field == literal_policy[0]
                     and spec.endpoints[int(literal_policy[0].split('.')[1])].allow_unknown_fields == literal_policy[1])
            and not (spec.deploy.enabled is False and item.field and (
                item.field.startswith("exposure.") or (item.field.startswith("deploy.") and item.field != "deploy.enabled")
            ))
        ]
        return review

    @staticmethod
    def _explicit_error_format(spec: ServiceSpec, field: str | None, request: str) -> bool:
        match = re.fullmatch(r"endpoints\.(\d+)\.error_field", field or "")
        if not match or int(match.group(1)) >= len(spec.endpoints):
            return False
        name = spec.endpoints[int(match.group(1))].error_field
        return bool(name and re.search(r"all errors[\s\S]{0,160}?field\s+(?:named\s+)?[\"']?" + re.escape(name) + r"\b", request, re.IGNORECASE))

    @staticmethod
    def _irrelevant_input_policy(spec: ServiceSpec, field: str | None) -> bool:
        match = re.fullmatch(r"endpoints\.(\d+)\.allow_unknown_fields", field or "")
        if not match or int(match.group(1)) >= len(spec.endpoints):
            return False
        endpoint = spec.endpoints[int(match.group(1))]
        return endpoint.method in {"GET", "HEAD"} and not endpoint.input_fields and not re.search(
            r"accept|input|query|body|参数|输入", endpoint.request_description or "", re.IGNORECASE)

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


def apply_grounded_corrections(spec: ServiceSpec, corrections: list[SpecCorrection], request: str, history: list[dict], protected_fields: set[str] | None = None) -> tuple[ServiceSpec, list[dict]]:
    """Accept exact-source scalar edits only. Quote matching is not semantic proof."""
    allowed = re.compile(r"^(service\.(name|module)|repo\.(owner|name)|endpoints\.\d+\.(allow_unknown_fields|success_status|malformed_json_status|validation_error_status|error_field|input_fields\.\d+\.(name|type|required|minimum|maximum)|business_rules\.\d+\.(name|expression|condition)))$")
    sources = [request] + [str(turn.get("answer", "")) for turn in history]
    accepted = []
    for correction in corrections[:8]:
        if correction.field in (protected_fields or set()):
            continue
        if not allowed.fullmatch(correction.field) or not AmbiguityAnalyzer._is_scalar_field(spec, correction.field):
            continue
        field_answers = [str(turn.get("answer", "")) for turn in history if turn.get("field") == correction.field]
        current_sources = field_answers[-1:] or sources
        if not any(correction.source_quote in source for source in current_sources):
            continue
        # Literal identifiers/statuses must themselves occur in the quoted source.
        if correction.field.startswith(("service.", "repo.")) and str(correction.value) not in correction.source_quote:
            continue
        if correction.field.endswith("_status") and not re.search(r"(?<!\d)" + re.escape(str(correction.value)) + r"(?!\d)", correction.source_quote):
            continue
        try:
            updated = apply_field_updates(spec, {correction.field: correction.value})
        except (TypeError, ValueError):
            continue
        if updated != spec:
            spec = updated
            accepted.append(correction.model_dump(mode="json"))
    return spec, accepted
