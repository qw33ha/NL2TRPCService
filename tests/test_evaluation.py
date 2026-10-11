from pathlib import Path
import pytest

from nl2service.build.verify import BuildVerificationResult
from nl2service.evaluation.runner import BlockedDelivery, load_tasks, run_task


def test_production_graph_interrupts_and_isolation(monkeypatch):
    from nl2service.render.renderer import ServiceRenderer
    roots = []
    write = ServiceRenderer.write_tree
    def capture(self, files, root):
        roots.append(root)
        return write(self, files, root)
    monkeypatch.setattr(ServiceRenderer, "write_tree", capture)
    monkeypatch.setattr("nl2service.build.verify.GoBuildVerifier.verify", lambda self, files: BuildVerificationResult(success=True))
    task = load_tasks(Path("nl2service/evaluation/tasks.jsonl"))[2]
    result = run_task(task)
    assert result["passed"], result
    assert result["interrupts"] == ["clarification", "approval", "github_approval"]
    assert "verify_build" in [entry["node"] for entry in result["trace"]]
    assert roots and all(not root.exists() for root in roots)


def test_missing_response_fails_report(monkeypatch):
    task = load_tasks(Path("nl2service/evaluation/tasks.jsonl"))[2]
    task.responses = []
    result = run_task(task)
    assert not result["passed"]
    assert "No scripted response" in result["error"]


def test_external_delivery_fails_closed():
    with pytest.raises(RuntimeError, match="forbids external delivery"):
        BlockedDelivery().commit_files("example/repo", {})


def test_duplicate_ids_rejected(tmp_path):
    path = tmp_path / "tasks.jsonl"
    path.write_text('{"id":"x","request":"x","spec":{}}\n' * 2)
    with pytest.raises(ValueError, match="unique"):
        load_tasks(path)


@pytest.mark.parametrize("path", ["../escape", "C:/escape", "/escape", "..\\escape"])
def test_generated_paths_cannot_escape(tmp_path, path):
    from nl2service.render.paths import safe_destination
    with pytest.raises(ValueError, match="Unsafe"):
        safe_destination(tmp_path, path)


def test_build_failure_is_reported_and_bounded(monkeypatch):
    monkeypatch.setattr("nl2service.build.verify.GoBuildVerifier.verify", lambda self, files: BuildVerificationResult(success=False, feedback="intentional build failure", exit_code=1))
    result = run_task(load_tasks(Path("nl2service/evaluation/tasks.jsonl"))[0])
    assert not result["passed"]
    assert "3 automatic repair attempts" in result["error"]
    assert "repair" in [item["node"] for item in result["trace"]]


def test_scoring_assertions_are_not_sent_to_repair(monkeypatch):
    from nl2service.evaluation.runner import EvaluationVerifier
    monkeypatch.setattr("nl2service.build.verify.GoBuildVerifier.verify", lambda self, files: BuildVerificationResult(success=True))
    def forbidden(*args):
        raise AssertionError("Scoring must not run inside build/repair")
    monkeypatch.setattr("nl2service.evaluation.runner.run_behavior", forbidden)
    verifier = EvaluationVerifier()
    result = verifier.verify({"handler.go": 'package handler\n// http.HandleFunc("/health", h.Health)\n'})
    assert result.success
    assert "standard library mux" not in result.feedback
    assert verifier.builds[0]["status"] == "passed"
    assert verifier.behaviors == []
