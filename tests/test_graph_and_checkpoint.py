from __future__ import annotations

from pathlib import Path

from nl2service.runtime.checkpointer import SQLiteCheckpointRuntime
from nl2service.spec.models import ServiceSpec
from nl2service.workflow.conversation_graph import ConversationalServiceWorkflow
from nl2service.workflow.core import WorkflowCore


def test_conversational_graph_compiles_with_checkpoint(tmp_path: Path) -> None:
    with SQLiteCheckpointRuntime(tmp_path / "agent.db") as runtime:
        workflow = ConversationalServiceWorkflow(WorkflowCore(), runtime.checkpointer)

        assert workflow.graph is not None


def test_checkpoint_serializer_round_trips_service_spec(tmp_path: Path) -> None:
    spec = ServiceSpec.model_validate(
        {
            "service": {"name": "checkpoint-service", "mode": "http"},
            "endpoints": [{"path": "/health", "method": "get"}],
        }
    )

    with SQLiteCheckpointRuntime(tmp_path / "agent.db") as runtime:
        payload = runtime.checkpointer.serde.dumps_typed(spec)
        restored = runtime.checkpointer.serde.loads_typed(payload)

    assert isinstance(restored, ServiceSpec)
    assert restored == spec
