from __future__ import annotations

from pathlib import Path

import yaml

from nl2service.spec.models import ServiceSpec
from nl2service.workflow.state import WorkflowState, structured_state_defaults


class WorkflowSessionStore:
    def save(self, state: WorkflowState, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(self._serialize(state), sort_keys=False, allow_unicode=True), encoding="utf-8")

    def load(self, path: Path) -> WorkflowState:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return self._deserialize(data)

    def _serialize(self, state: WorkflowState) -> dict:
        data = dict(state)
        draft_spec = data.get("draft_spec")
        if isinstance(draft_spec, ServiceSpec):
            data["draft_spec"] = draft_spec.model_dump(mode="json", exclude_none=True)
        return data

    def _deserialize(self, data: dict) -> WorkflowState:
        structured = structured_state_defaults()
        loaded: WorkflowState = {
            "user_request": data.get("user_request", ""),
            "model": data.get("model"),
            "target_phase": data.get("target_phase", "draft"),
            "additional_context": data.get("additional_context", []),
            "clarification_history": data.get("clarification_history", []),
            "notes": data.get("notes", []),
            "extracted_fields": data.get("extracted_fields", []),
            "gate_confirmed": bool(data.get("gate_confirmed", False)),
            "interaction": data.get("interaction"),
            "validation_issues": data.get("validation_issues", []),
            "clarification_items": data.get("clarification_items", []),
            "gate_summary_lines": data.get("gate_summary_lines", []),
            "proto_summary_lines": data.get("proto_summary_lines", []),
            "verification_summary_lines": data.get("verification_summary_lines", []),
            "build_feedback": data.get("build_feedback"),
            "verification_attempts": int(data.get("verification_attempts", 0)),
            "rendered_files": data.get("rendered_files", {}),
            "refinement_notes": data.get("refinement_notes", []),
            "output_dir": data.get("output_dir"),
            "github_delivery": data.get("github_delivery", {}),
            "github_summary_lines": data.get("github_summary_lines", []),
            "selected_examples": data.get("selected_examples", structured["selected_examples"]),
            "example_reference_files": data.get(
                "example_reference_files", structured["example_reference_files"]
            ),
            "local_build": data.get("local_build", structured["local_build"]),
            "active_failure": data.get("active_failure"),
            "repair_history": data.get("repair_history", structured["repair_history"]),
            "ci_run": data.get("ci_run", structured["ci_run"]),
            "deployment": data.get("deployment", structured["deployment"]),
            "delivery_report": data.get("delivery_report", structured["delivery_report"]),
            "status": data.get("status", "starting"),
            "error": data.get("error"),
        }
        if data.get("draft_spec"):
            loaded["draft_spec"] = ServiceSpec.model_validate(data["draft_spec"])
        return loaded
