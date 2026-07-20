from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from nl2service.render.renderer import ProtoContractError
from nl2service.workflow.graph import NL2ServiceWorkflow
from nl2service.workflow.state import WorkflowState, clarification_to_dict
from nl2service.workflow.updates import apply_field_updates


class ConversationalServiceWorkflow:
    """Native-interrupt graph used by the user-facing agent session."""

    def __init__(self, core: NL2ServiceWorkflow, checkpointer: Any) -> None:
        self.core = core
        self.graph = self._build_graph().compile(checkpointer=checkpointer)

    def _build_graph(self) -> StateGraph:
        graph = StateGraph(WorkflowState)
        graph.add_node("build_spec", self.core._build_spec_node)
        graph.add_node("analyze_ambiguity", self._analyze_ambiguity_node)
        graph.add_node("validate_spec", self.core._validate_spec_node)
        graph.add_node("clarify", self._clarify_node)
        graph.add_node("approve_plan", self._approval_node)
        graph.add_node("ensure_proto", self._ensure_proto_node)
        graph.add_node("render_project", self.core._render_project_node)
        graph.add_node("select_examples", self.core._select_examples_node)
        graph.add_node("refine_code", self.core._refine_code_node)
        graph.add_node("verify_build", self.core._verify_build_node)
        graph.add_node("repair", self.core._repair_build_errors_node)
        graph.add_node("approve_github", self._github_approval_node)
        graph.add_node("deliver_to_github", self.core._deliver_to_github_node)
        graph.add_node("await_github_actions", self._await_github_actions_node)
        graph.add_node("prepare_delivery_report", self.core.github_actions.prepare_report)

        graph.add_edge(START, "build_spec")
        graph.add_edge("build_spec", "analyze_ambiguity")
        graph.add_edge("analyze_ambiguity", "validate_spec")
        graph.add_conditional_edges(
            "validate_spec",
            self._route_after_validation,
            {"clarify": "clarify", "approve_plan": "approve_plan", "end": END},
        )
        graph.add_edge("clarify", "analyze_ambiguity")
        graph.add_conditional_edges(
            "approve_plan",
            self._route_after_approval,
            {"ensure_proto": "ensure_proto", "validate": "analyze_ambiguity", "end": END},
        )
        graph.add_conditional_edges(
            "ensure_proto",
            lambda state: "render_project" if state.get("status") == "proto_ready" else "end",
            {"render_project": "render_project", "end": END},
        )
        graph.add_edge("render_project", "select_examples")
        graph.add_edge("select_examples", "refine_code")
        graph.add_edge("refine_code", "verify_build")
        graph.add_conditional_edges(
            "verify_build",
            self._route_after_build,
            {
                "repair": "repair",
                "verify_build": "verify_build",
                "approve_github": "approve_github",
                "deliver": "deliver_to_github",
                "end": END,
            },
        )
        graph.add_edge("repair", "verify_build")
        graph.add_conditional_edges(
            "approve_github",
            self._route_after_github_approval,
            {"deliver": "deliver_to_github", "validate": "analyze_ambiguity", "end": END},
        )
        graph.add_edge("deliver_to_github", "await_github_actions")
        graph.add_conditional_edges(
            "await_github_actions",
            self.core.github_actions.route,
            {
                "repair_build_errors": "repair",
                "prepare_delivery_report": "prepare_delivery_report",
                "end": END,
            },
        )
        graph.add_edge("prepare_delivery_report", END)
        return graph

    @staticmethod
    def _route_after_validation(state: WorkflowState) -> str:
        if state.get("error"):
            return "end"
        if any(issue.get("severity") == "error" for issue in state.get("validation_issues", [])):
            return "clarify"
        if any(item.get("priority") in {"blocking", "important"} for item in state.get("ambiguity_items", [])):
            return "clarify"
        return "approve_plan"

    def _analyze_ambiguity_node(self, state: WorkflowState) -> WorkflowState:
        spec = state.get("draft_spec")
        if spec is None:
            state["status"] = "error"
            state["error"] = "No draft specification is available for ambiguity analysis."
            return state
        try:
            review = self.core.ambiguity_analyzer.analyze(
                state.get("user_request", ""),
                spec,
                list(state.get("clarification_history", [])),
                list(state.get("resolved_ambiguities", [])),
            )
        except Exception as exc:
            state["status"] = "error"
            state["error"] = f"Ambiguity analysis failed: {exc}"
            return state
        resolved = set(state.get("resolved_ambiguities", []))
        asked_questions = {
            str(turn.get("question", "")).strip().lower()
            for turn in state.get("clarification_history", [])
        }
        fresh_items = [
            item for item in review.items
            if item.key not in resolved and item.question.strip().lower() not in asked_questions
        ][:5]
        state["last_agent_action"] = "analyze_ambiguity"
        state["agent_notes"] = ["Conversation workflow reviewed the current spec for unresolved ambiguities."]
        state["ambiguity_items"] = [item.model_dump(mode="json") for item in fresh_items]
        optional_assumptions = [item.reason for item in fresh_items if item.priority == "optional"]
        state["accepted_assumptions"] = list(
            dict.fromkeys([*review.assumptions, *optional_assumptions])
        )
        state["status"] = "ambiguity_analyzed"
        state["error"] = None
        return state

    def _clarify_node(self, state: WorkflowState) -> WorkflowState:
        spec = state.get("draft_spec")
        if spec is None:
            state["status"] = "error"
            state["error"] = "No draft specification is available."
            return state
        session = self.core.clarifier.build(spec)
        ambiguity = next(
            (
                item for item in state.get("ambiguity_items", [])
                if item.get("priority") in {"blocking", "important"}
            ),
            None,
        )
        if session.items:
            item = session.items[0]
            item_data = clarification_to_dict(item)
        elif ambiguity is not None:
            item = None
            item_data = {
                "field": str(ambiguity.get("field") or ""),
                "question": str(ambiguity.get("question", "")),
                "reason": str(ambiguity.get("reason", "")),
                "severity": str(ambiguity.get("priority", "important")),
                "ambiguity_key": str(ambiguity.get("key", "")),
            }
        else:
            state["status"] = "validated"
            return state
        state["last_agent_action"] = "ask_clarification"
        state["agent_notes"] = ["Conversation workflow is waiting on a targeted clarification before continuing."]
        state["clarification_items"] = [item_data]
        response = interrupt(
            {
                "kind": "clarification",
                "field": item_data["field"],
                "question": item_data["question"],
                "reason": item_data["reason"],
                "ambiguity_key": item_data.get("ambiguity_key"),
            }
        )
        if isinstance(response, dict) and response.get("cancelled"):
            state["status"] = "cancelled"
            state["error"] = None
            return state
        if isinstance(response, dict) and response.get("field_updates"):
            updates = dict(response["field_updates"])
            state["draft_spec"] = apply_field_updates(spec, updates)
            history = list(state.get("clarification_history", []))
            raw_answer = str(response.get("raw_answer") or f"Corrected fields: {', '.join(updates)}")
            history.append({"question": item_data["question"], "answer": raw_answer})
            state["clarification_history"] = history
            ambiguity_key = item_data.get("ambiguity_key")
            if ambiguity_key and item_data["field"] in updates:
                state["resolved_ambiguities"] = list(
                    dict.fromkeys([*state.get("resolved_ambiguities", []), ambiguity_key])
                )
            state["clarification_items"] = []
            state["status"] = "clarification_applied"
            state["error"] = None
            return state
        answer = response.get("answer") if isinstance(response, dict) else response
        if answer == "__DISABLE_DATABASE__":
            state["draft_spec"] = apply_field_updates(spec, {"database.enabled": False})
            state["clarification_items"] = []
            state["status"] = "clarification_applied"
            state["error"] = None
            return state
        if answer == "__DISABLE_KAFKA__":
            state["draft_spec"] = apply_field_updates(spec, {"kafka.enabled": False})
            state["clarification_items"] = []
            state["status"] = "clarification_applied"
            state["error"] = None
            return state
        if answer in (None, "", [], {}):
            state["status"] = "error"
            state["error"] = f"No answer was provided for {item_data['field']}."
            return state
        if item_data.get("ambiguity_key") or (isinstance(response, dict) and response.get("contextual")):
            history = list(state.get("clarification_history", []))
            raw_answer = response.get("raw_answer") if isinstance(response, dict) else None
            history.append({"question": item_data["question"], "answer": str(raw_answer or answer)})
            state["clarification_history"] = history
            state["resolved_ambiguities"] = list(
                dict.fromkeys([*state.get("resolved_ambiguities", []), item_data["ambiguity_key"]])
            )
            state["clarification_items"] = []
            state["status"] = "clarification_applied"
            state["error"] = None
            return state
        state["draft_spec"] = apply_field_updates(spec, {item_data["field"]: answer})
        history = list(state.get("clarification_history", []))
        raw_answer = response.get("raw_answer") if isinstance(response, dict) else None
        history.append({"question": item_data["question"], "answer": str(raw_answer or answer)})
        state["clarification_history"] = history
        ambiguity_key = item_data.get("ambiguity_key")
        if ambiguity_key:
            state["resolved_ambiguities"] = list(
                dict.fromkeys([*state.get("resolved_ambiguities", []), ambiguity_key])
            )
        state["clarification_items"] = []
        state["status"] = "clarification_applied"
        state["error"] = None
        return state

    def _approval_node(self, state: WorkflowState) -> WorkflowState:
        spec = state.get("draft_spec")
        if spec is None:
            state["status"] = "error"
            state["error"] = "No specification is available for approval."
            return state
        summary = self.core.gate_builder.build(spec).to_lines()
        summary.extend(f"Assumption: {item}" for item in state.get("accepted_assumptions", []))
        state["last_agent_action"] = "request_approval"
        state["agent_notes"] = ["Conversation workflow prepared a gate summary and is requesting user approval."]
        state["gate_summary_lines"] = summary
        response = interrupt({"kind": "approval", "question": "Should I generate and build this service?", "summary": summary})
        if isinstance(response, dict) and response.get("field_updates"):
            state["draft_spec"] = apply_field_updates(spec, dict(response["field_updates"]))
            state["gate_confirmed"] = False
            state["status"] = "approval_updated"
            state["error"] = None
            return state
        confirmed = response.get("confirmed") if isinstance(response, dict) else response
        state["gate_confirmed"] = bool(confirmed)
        state["status"] = "gate_confirmed" if confirmed else "cancelled"
        state["error"] = None
        return state

    @staticmethod
    def _route_after_approval(state: WorkflowState) -> str:
        if state.get("status") == "approval_updated":
            return "validate"
        if state.get("gate_confirmed"):
            return "ensure_proto"
        return "end"

    def _ensure_proto_node(self, state: WorkflowState) -> WorkflowState:
        spec = state.get("draft_spec")
        if spec is None:
            state["status"] = "error"
            state["error"] = "No specification is available for protocol validation."
            return state
        state["last_agent_action"] = "ensure_proto"
        state["agent_notes"] = ["Conversation workflow is checking whether a proto contract is required before rendering."]
        if not spec.service.enable_trpc:
            state["status"] = "proto_ready"
            return state
        while True:
            proto_file = str(spec.service.proto_file or "").strip()
            if proto_file:
                try:
                    self.core.renderer.inspect_contract(spec)
                    state["status"] = "proto_ready"
                    state["error"] = None
                    return state
                except ProtoContractError:
                    pass
            response = interrupt(
                {
                    "kind": "proto",
                    "question": "Please provide the path to the .proto contract file.",
                }
            )
            value = response.get("path") if isinstance(response, dict) else response
            spec = apply_field_updates(spec, {"service.proto_file": str(value or "").strip()})
            state["draft_spec"] = spec

    @staticmethod
    def _route_after_build(state: WorkflowState) -> str:
        if state.get("status") == "verified":
            delivery = state.get("github_delivery", {})
            if delivery.get("owner") and delivery.get("repo"):
                return "deliver"
            return "approve_github"
        if state.get("status") == "build_verification_failed":
            return "repair"
        if state.get("status") == "deterministic_repair_applied":
            return "verify_build"
        return "end"

    def _github_approval_node(self, state: WorkflowState) -> WorkflowState:
        spec = state.get("draft_spec")
        if spec is None:
            state["status"] = "error"
            state["error"] = "No specification is available for GitHub delivery."
            return state
        state["last_agent_action"] = "request_github_delivery"
        state["agent_notes"] = ["Conversation workflow is requesting confirmation before GitHub delivery."]
        response = interrupt(
            {
                "kind": "github_approval",
                "question": f"Local build passed. Should I commit directly to {spec.repo.owner}/{spec.repo.name}?",
                "owner": spec.repo.owner,
                "repo": spec.repo.name,
            }
        )
        if isinstance(response, dict) and response.get("field_updates"):
            state["draft_spec"] = apply_field_updates(spec, dict(response["field_updates"]))
            state["status"] = "approval_updated"
            state["error"] = None
            return state
        confirmed = response.get("confirmed") if isinstance(response, dict) else response
        if not confirmed:
            state["status"] = "verified"
            return state
        payload = response if isinstance(response, dict) else {}
        state["github_delivery"] = {
            "owner": payload.get("owner") or spec.repo.owner,
            "repo": payload.get("repo") or spec.repo.name,
            "create_repo": bool(payload.get("create_repo", True)),
            "commit_message": payload.get("commit_message") or "Add generated NL2Service application",
        }
        state["status"] = "github_delivery_configured"
        return state

    @staticmethod
    def _route_after_github_approval(state: WorkflowState) -> str:
        if state.get("status") == "approval_updated":
            return "validate"
        if state.get("status") == "github_delivery_configured":
            return "deliver"
        return "end"

    def _await_github_actions_node(self, state: WorkflowState) -> WorkflowState:
        while True:
            delivery = dict(state.get("github_delivery", {}))
            signal = interrupt(
                {
                    "kind": "external_wait",
                    "source": "github_actions",
                    "question": "GitHub Actions is running. I will continue when the run completes.",
                    "github_delivery": delivery,
                    "owner": delivery.get("owner"),
                    "repo": delivery.get("repo"),
                    "commit_sha": delivery.get("commit_sha"),
                }
            )
            is_poll = signal in ("poll", True) or (
                isinstance(signal, dict) and signal.get("type") == "poll"
            )
            if not is_poll:
                state["status"] = "awaiting_github_actions"
                return state
            if isinstance(signal, dict):
                persisted_delivery = signal.get("github_delivery")
                if isinstance(persisted_delivery, dict):
                    state["github_delivery"] = dict(persisted_delivery)
                else:
                    state["github_delivery"] = {
                        **delivery,
                        "owner": signal.get("owner") or delivery.get("owner"),
                        "repo": signal.get("repo") or delivery.get("repo"),
                        "commit_sha": signal.get("commit_sha") or delivery.get("commit_sha"),
                    }
            state = self.core.github_actions.monitor(state)
            if state.get("status") != "awaiting_github_actions":
                return state
