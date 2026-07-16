from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from langgraph.types import Command

from nl2service.agent.events import AgentEvent, AgentTurn
from nl2service.agent.conversation import ClarificationInterpreter
from nl2service.agent.provider import LLMProvider
from nl2service.runtime.checkpointer import SQLiteCheckpointRuntime
from nl2service.tools.github_tool import GitHubApiProvider, GitHubProvider
from nl2service.workflow.conversation_graph import ConversationalServiceWorkflow
from nl2service.workflow.graph import NL2ServiceWorkflow
from nl2service.workflow.state import WorkflowState, structured_state_defaults


class AgentSession:
    def __init__(
        self,
        model: str | None = None,
        provider: LLMProvider | None = None,
        github_provider: GitHubProvider | None = None,
        database_path: Path | None = None,
    ) -> None:
        self.model = model
        self.runtime = SQLiteCheckpointRuntime(database_path)
        self.core = NL2ServiceWorkflow(
            model=model,
            provider=provider or LLMProvider(),
            github_provider=github_provider or GitHubApiProvider(),
        )
        self.workflow = ConversationalServiceWorkflow(self.core, self.runtime.checkpointer)
        self.clarification_interpreter = ClarificationInterpreter(self.core.provider, model)

    @staticmethod
    def new_thread_id() -> str:
        return str(uuid4())

    def handle_message(self, thread_id: str, message: str) -> AgentTurn:
        config = self._config(thread_id)
        snapshot = self.workflow.graph.get_state(config)
        pending = self._pending_interrupt(snapshot)
        if pending is None and not snapshot.values:
            if not message.strip():
                return AgentTurn(
                    thread_id=thread_id,
                    events=[AgentEvent("question", "What service would you like me to build?")],
                    status="awaiting_request",
                    waiting_for="request",
                )
            try:
                result = self.workflow.graph.invoke(self._initial_state(message, thread_id), config=config)
            except Exception as exc:
                return self._failure_turn(thread_id, exc)
        elif pending is not None:
            if pending.get("kind") == "external_wait":
                try:
                    result = self.workflow.graph.invoke(
                        Command(resume={**pending, "type": "poll"}),
                        config=config,
                    )
                except Exception as exc:
                    return self._failure_turn(thread_id, exc)
                return self._turn_from_result(thread_id, result, config)
            resume_value = self._interpret_reply(pending, message, dict(snapshot.values))
            if isinstance(resume_value, AgentEvent):
                return AgentTurn(thread_id, [resume_value], "waiting_for_user", pending.get("kind"))
            try:
                result = self.workflow.graph.invoke(Command(resume=resume_value), config=config)
            except Exception as exc:
                return self._failure_turn(thread_id, exc)
        else:
            state = dict(snapshot.values)
            return AgentTurn(
                thread_id=thread_id,
                events=self._events_for_state(state),
                status=str(state.get("status", "complete")),
            )
        return self._turn_from_result(thread_id, result, config)

    def resume_external(self, thread_id: str, event: dict[str, Any]) -> AgentTurn:
        config = self._config(thread_id)
        snapshot = self.workflow.graph.get_state(config)
        pending = self._pending_interrupt(snapshot)
        if pending is None or pending.get("kind") != "external_wait":
            state = dict(snapshot.values)
            return AgentTurn(thread_id, self._events_for_state(state), str(state.get("status", "idle")))
        resume_event = {**pending, **event}
        try:
            result = self.workflow.graph.invoke(Command(resume=resume_event), config=config)
        except Exception as exc:
            return self._failure_turn(thread_id, exc)
        return self._turn_from_result(thread_id, result, config)

    def get_state(self, thread_id: str) -> WorkflowState | None:
        snapshot = self.workflow.graph.get_state(self._config(thread_id))
        return dict(snapshot.values) if snapshot.values else None

    def close(self) -> None:
        self.runtime.close()

    def _turn_from_result(self, thread_id: str, result: dict[str, Any], config: dict[str, Any]) -> AgentTurn:
        snapshot = self.workflow.graph.get_state(config)
        pending = self._pending_interrupt(snapshot)
        state = dict(snapshot.values or result)
        if pending is not None:
            event = self._event_for_interrupt(pending)
            return AgentTurn(thread_id, [event], str(state.get("status", "interrupted")), pending.get("kind"))
        return AgentTurn(thread_id, self._events_for_state(state), str(state.get("status", "complete")))

    def _initial_state(self, request: str, thread_id: str) -> WorkflowState:
        state: dict[str, Any] = {
            **structured_state_defaults(),
            "user_request": request,
            "model": self.model,
            "target_phase": "deliver",
            "additional_context": [],
            "clarification_history": [],
            "notes": [],
            "extracted_fields": [],
            "gate_confirmed": False,
            "interaction": None,
            "validation_issues": [],
            "clarification_items": [],
            "gate_summary_lines": [],
            "proto_summary_lines": [],
            "verification_summary_lines": [],
            "build_feedback": None,
            "verification_attempts": 0,
            "rendered_files": {},
            "refinement_notes": [],
            "output_dir": str(Path("generated") / thread_id),
            "github_delivery": {},
            "github_summary_lines": [],
            "status": "starting",
            "error": None,
        }
        return state  # type: ignore[return-value]

    @staticmethod
    def _config(thread_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": thread_id}}

    @staticmethod
    def _pending_interrupt(snapshot: Any) -> dict[str, Any] | None:
        for task in getattr(snapshot, "tasks", ()):
            for item in getattr(task, "interrupts", ()):
                value = getattr(item, "value", None)
                if isinstance(value, dict):
                    return value
        return None

    def _interpret_reply(
        self,
        pending: dict[str, Any],
        message: str,
        state: dict[str, Any] | None = None,
    ) -> Any:
        kind = pending.get("kind")
        text = message.strip()
        if kind == "clarification":
            field = str(pending.get("field") or "")
            is_contextual_answer = bool(pending.get("ambiguity_key"))
            try:
                decision = self.clarification_interpreter.route_turn(
                    pending,
                    text,
                    (state or {}).get("draft_spec"),
                    self._conversation_context(state),
                )
            except Exception:
                decision = None
            if decision is not None:
                if decision.intent == "question":
                    return AgentEvent(
                        "message",
                        decision.response or "I need a little more context to answer that question.",
                    )
                if decision.intent == "cancel":
                    return {"cancelled": True}
                if decision.intent == "correct":
                    updates: dict[str, Any] = {}
                    for update in decision.updates:
                        try:
                            value = json.loads(update.value_json)
                        except (TypeError, ValueError):
                            value = update.value_json
                        updates[update.field] = self.clarification_interpreter._normalize(update.field, value)
                    if updates:
                        return {"field_updates": updates, "raw_answer": text}
                if decision.intent == "answer" and decision.answer_json is not None:
                    try:
                        value = json.loads(decision.answer_json)
                    except (TypeError, ValueError):
                        value = decision.answer_json
                    if value is None and field in {"database.secret_name", "kafka.secret_name"}:
                        dependency = "database" if field.startswith("database.") else "Kafka"
                        return AgentEvent(
                            "question",
                            f"The deployed {dependency} integration currently requires a Kubernetes Secret. "
                            f"You can provide its lowercase name, explain another authentication method, or ask "
                            f"me to disable {dependency.lower()}.",
                        )
                    return {
                        "answer": text if is_contextual_answer else self.clarification_interpreter._normalize(field, value, text),
                        "raw_answer": text,
                        "contextual": is_contextual_answer,
                    }
            if is_contextual_answer:
                return {"answer": text, "raw_answer": text, "contextual": True}
            return {
                "answer": self.clarification_interpreter.interpret(
                    field,
                    str(pending.get("question") or ""),
                    text,
                ),
                "raw_answer": text,
            }
        if kind == "proto":
            return {"path": text}
        if kind in {"approval", "github_approval"}:
            normalized_confirmation = text.lower().rstrip(".!?")
            explicit_stop = normalized_confirmation in {
                "stop",
                "cancel",
                "quit",
                "end",
                "end the conversation",
                "do not continue",
                "don't continue",
            }
            try:
                decision = self.clarification_interpreter.route_confirmation(
                    pending,
                    text,
                    (state or {}).get("draft_spec"),
                    self._conversation_context(state),
                )
            except Exception:
                decision = None
            if explicit_stop:
                decision_value = False
            elif decision is not None:
                if decision.intent == "question":
                    return AgentEvent(
                        "message",
                        decision.response or "What would you like to know before deciding?",
                    )
                if decision.intent == "cancel":
                    decision_value: bool | None = False if explicit_stop else None
                elif decision.intent == "correct":
                    updates: dict[str, Any] = {}
                    for update in decision.updates:
                        try:
                            value = json.loads(update.value_json)
                        except (TypeError, ValueError):
                            value = update.value_json
                        updates[update.field] = self.clarification_interpreter._normalize(update.field, value)
                    if updates:
                        return {"field_updates": updates}
                    return AgentEvent("question", decision.response or "What should I change before proceeding?")
                elif decision.intent == "answer" and decision.answer_json is not None:
                    try:
                        parsed_decision = json.loads(decision.answer_json)
                    except (TypeError, ValueError):
                        parsed_decision = decision.answer_json
                    decision_value = parsed_decision if isinstance(parsed_decision, bool) else None
                else:
                    decision_value = None
            else:
                decision_value = None
            if normalized_confirmation in {"no", "n", "nope", "not yet"}:
                return AgentEvent(
                    "question",
                    "No problem—I won't proceed with the current proposal. What would you like me to change or explain?",
                )
            if decision_value is None:
                decision_value = self._yes_no(text)
            if decision_value is None:
                return AgentEvent("question", "Please answer yes or no so I can apply the approval gate safely.")
            payload: dict[str, Any] = {"confirmed": decision_value}
            if kind == "github_approval":
                payload.update(
                    {
                        "owner": pending.get("owner"),
                        "repo": pending.get("repo"),
                        "create_repo": True,
                    }
                )
            return payload
        if kind == "external_wait":
            return AgentEvent("progress", "GitHub Actions is still being monitored in the background.")
        return text

    @staticmethod
    def _conversation_context(state: dict[str, Any] | None) -> dict[str, Any]:
        state = state or {}
        return {
            "original_request": state.get("user_request", ""),
            "clarification_history": list(state.get("clarification_history", []))[-20:],
            "agent_notes": list(state.get("notes", []))[-10:],
        }

    @staticmethod
    def _yes_no(text: str) -> bool | None:
        normalized = text.strip().lower().rstrip(".!?")
        if normalized in {"yes", "y", "yeah", "yep", "sure", "ok", "okay", "approve", "approved", "continue"}:
            return True
        if normalized in {"no", "n", "nope", "cancel", "stop", "reject", "rejected"}:
            return False
        return None

    @staticmethod
    def _event_for_interrupt(payload: dict[str, Any]) -> AgentEvent:
        kind = payload.get("kind")
        question = str(payload.get("question") or "I need more information.")
        if kind in {"approval", "github_approval"}:
            return AgentEvent("approval", question, payload)
        if kind == "external_wait":
            return AgentEvent("external_wait", question, payload)
        return AgentEvent("question", question, payload)

    @staticmethod
    def _events_for_state(state: dict[str, Any]) -> list[AgentEvent]:
        if state.get("error"):
            return [AgentEvent("error", str(state["error"]))]
        if state.get("status") == "complete":
            deployment_status = state.get("deployment", {}).get("status")
            message = (
                "The service was generated, built, and published successfully; Kubernetes deployment was skipped."
                if deployment_status == "skipped"
                else "The service was generated, built, published, and deployed successfully."
            )
            return [
                AgentEvent(
                    "completed",
                    message,
                    dict(state.get("delivery_report", {})),
                )
            ]
        if state.get("status") == "cancelled":
            return [AgentEvent("message", "Okay, I stopped before making the approved external change.")]
        if state.get("status") == "verified":
            return [AgentEvent("message", "The local build passed. The generated files are ready.")]
        return [AgentEvent("progress", f"Workflow status: {state.get('status', 'unknown')}")]

    @staticmethod
    def _failure_turn(thread_id: str, exc: Exception) -> AgentTurn:
        return AgentTurn(
            thread_id=thread_id,
            events=[AgentEvent("error", f"The agent could not continue: {exc}")],
            status="error",
        )
