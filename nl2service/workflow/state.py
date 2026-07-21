from __future__ import annotations

from typing import Any, Literal

from typing_extensions import NotRequired, TypedDict

from nl2service.spec.models import ServiceSpec


class WorkflowState(TypedDict):
    user_request: str
    model: str | None
    target_phase: str
    agent_notes: list[str]
    additional_context: list[str]
    clarification_history: list[dict[str, str]]
    gate_confirmed: bool
    draft_spec: NotRequired[ServiceSpec]
    validation_issues: list[dict[str, str]]
    clarification_items: list[dict[str, str]]
    ambiguity_items: list[dict[str, Any]]
    resolved_ambiguities: list[str]
    accepted_assumptions: list[str]
    gate_summary_lines: list[str]
    verification_summary_lines: list[str]
    build_feedback: str | None
    verification_attempts: int
    rendered_files: dict[str, str]
    refinement_notes: list[str]
    output_dir: str | None
    github_delivery: dict[str, Any]
    selected_examples: list[str]
    example_reference_files: dict[str, str]
    local_build: "BuildState"
    active_failure: "FailureState | None"
    repair_history: list["RepairRecord"]
    ci_run: "CIRunState"
    deployment: "DeploymentState"
    delivery_report: "DeliveryReportState"
    status: str
    error: str | None


class BuildState(TypedDict):
    status: Literal["pending", "passed", "failed"]
    command: str | None
    exit_code: int | None
    logs: str
    attempt: int


class FailureState(TypedDict):
    source: Literal["local_build", "github_ci", "deployment"]
    stage: str
    command: str | None
    exit_code: int | None
    logs: str
    run_id: str | None
    commit_sha: str | None
    signature: NotRequired[str]


class RepairRecord(TypedDict):
    source: str
    stage: str
    attempt: int
    changed_files: list[str]
    feedback: str
    signature: NotRequired[str | None]


class CIRunState(TypedDict):
    run_id: str | None
    url: str | None
    commit_sha: str | None
    status: str
    conclusion: str | None
    failed_job: str | None
    logs: str | None
    poll_attempts: int


class DeploymentState(TypedDict):
    status: str
    environment: str | None
    namespace: str | None
    deployment: str | None
    image: str | None
    image_digest: str | None
    endpoint: str | None


class DeliveryReportState(TypedDict):
    repository_url: str | None
    branch: str | None
    commit_sha: str | None
    action_run_url: str | None
    image: str | None
    image_digest: str | None
    environment: str | None
    deployment: str | None
    endpoint: str | None
    secret_names: list[str]
    database_tables: list[str]
    kafka_topics: list[str]
    usage_examples: list[str]
    warnings: list[str]


def structured_state_defaults() -> dict[str, Any]:
    return {
        "agent_notes": [],
        "ambiguity_items": [],
        "resolved_ambiguities": [],
        "accepted_assumptions": [],
        "selected_examples": [],
        "example_reference_files": {},
        "local_build": {
            "status": "pending",
            "command": None,
            "exit_code": None,
            "logs": "",
            "attempt": 0,
        },
        "active_failure": None,
        "repair_history": [],
        "ci_run": {
            "run_id": None,
            "url": None,
            "commit_sha": None,
            "status": "pending",
            "conclusion": None,
            "failed_job": None,
            "logs": None,
            "poll_attempts": 0,
        },
        "deployment": {
            "status": "pending",
            "environment": None,
            "namespace": None,
            "deployment": None,
            "image": None,
            "image_digest": None,
            "endpoint": None,
        },
        "delivery_report": {
            "repository_url": None,
            "branch": None,
            "commit_sha": None,
            "action_run_url": None,
            "image": None,
            "image_digest": None,
            "environment": None,
            "deployment": None,
            "endpoint": None,
            "secret_names": [],
            "database_tables": [],
            "kafka_topics": [],
            "usage_examples": [],
            "warnings": [],
        },
    }



def issue_to_dict(issue: Any) -> dict[str, str]:
    return {
        "field": str(getattr(issue, "field", "")),
        "message": str(getattr(issue, "message", "")),
        "severity": str(getattr(issue, "severity", "error")),
    }



def clarification_to_dict(item: Any) -> dict[str, str]:
    return {
        "field": str(getattr(item, "field", "")),
        "question": str(getattr(item, "question", "")),
        "reason": str(getattr(item, "reason", "")),
        "severity": str(getattr(item, "severity", "error")),
    }
