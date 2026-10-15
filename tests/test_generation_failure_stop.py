from langgraph.types import Command

from nl2service.agent.main_agent import MainAgentError, MainLLMAgent
from nl2service.evaluation.runner import ReplayProvider, BlockedDelivery
from nl2service.runtime.checkpointer import SQLiteCheckpointRuntime
from nl2service.workflow.core import WorkflowCore
from nl2service.workflow.conversation_graph import ConversationalServiceWorkflow


def test_failed_generation_cannot_be_hidden_by_compiling_placeholder_scaffold(tmp_path, monkeypatch):
    spec = {"service": {"name": "failure-stop", "module": "example.com/failure-stop", "mode": "http"},
        "endpoints": [{"path": "/status", "method": "GET"}],
        "repo": {"owner": "example", "name": "failure-stop"}, "deploy": {"enabled": False}}
    core = WorkflowCore(provider=ReplayProvider(spec), github_provider=BlockedDelivery())
    class MustNotVerify:
        def verify(self, files):
            raise AssertionError("A failed refinement must not verify a placeholder or attempt delivery")
    core.verifier = MustNotVerify()
    def fail(self, session):
        raise MainAgentError("provider timed out")
    monkeypatch.setattr(MainLLMAgent, "refine_code", fail)
    with SQLiteCheckpointRuntime(tmp_path / "state.db") as runtime:
        graph = ConversationalServiceWorkflow(core, runtime.checkpointer).graph
        config = {"configurable": {"thread_id": "failure-stop"}}
        first = graph.invoke({"user_request": "HTTP status", "model": None}, config)
        assert first["__interrupt__"][0].value["kind"] == "approval"
        final = graph.invoke(Command(resume={"confirmed": True}), config)
    assert final["status"] == "error" and final["error"] == "provider timed out"
    assert not final.get("github_delivery")
