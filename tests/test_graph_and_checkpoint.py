from __future__ import annotations

from pathlib import Path

from nl2service.runtime.checkpointer import SQLiteCheckpointRuntime
from nl2service.spec.models import ServiceSpec
from nl2service.workflow.conversation_graph import ConversationalServiceWorkflow
from nl2service.workflow.core import WorkflowCore
from nl2service.tools.github_tool import GitHubAPIError


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


def test_failed_delivery_preserves_error_without_entering_monitor(tmp_path: Path, http_spec) -> None:
    from unittest.mock import Mock
    from nl2service.workflow.state import structured_state_defaults

    provider = Mock()
    provider.create_repo.side_effect = GitHubAPIError('GITHUB_TOKEN is required for GitHub delivery.')
    with SQLiteCheckpointRuntime(tmp_path / 'delivery.db') as runtime:
        workflow = ConversationalServiceWorkflow(WorkflowCore(github_provider=provider), runtime.checkpointer)
        config = {'configurable': {'thread_id': 'failed-delivery'}}
        workflow.graph.update_state(config, {
            **structured_state_defaults(),
            'draft_spec': http_spec,
            'rendered_files': {'go.mod': 'module example.com/demo'},
            'github_delivery': {'owner': 'example', 'repo': 'demo'},
            'status': 'github_delivery_configured',
        }, as_node='approve_github')
        result = workflow.graph.invoke(None, config=config)
        assert result['status'] == 'error'
        assert result['error'] == 'GITHUB_TOKEN is required for GitHub delivery.'
        assert not workflow.graph.get_state(config).tasks
        provider.commit_files.assert_not_called()
        provider.get_workflow_run_for_commit.assert_not_called()
