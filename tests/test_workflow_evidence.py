from pathlib import Path

from nl2service.agent.main_agent import MainLLMAgent, RefinementResult
from nl2service.build.verify import BuildVerificationResult
from nl2service.evaluation.runner import load_tasks, run_task
from nl2service.evaluation.workflow_metrics import workflow_metrics


def task(index):
    return load_tasks(Path("nl2service/evaluation/tasks.jsonl"))[index]


def test_repair_graph_receives_diagnostic_changes_files_and_rechecks(monkeypatch):
    diagnostics = []
    original = MainLLMAgent.refine_code

    def refine(self, session):
        if "handler/evaluation_fault.go" in session.rendered_files:
            diagnostics.append(session.repair_feedback)
            return RefinementResult(
                files={**session.rendered_files, "handler/evaluation_fault.go": "package handler\n"},
                notes=["Remove invalid symbol"], model="controlled-test")
        return original(self, session)

    def verify(self, files):
        bad = "missingEvaluationSymbol" in files.get("handler/evaluation_fault.go", "")
        return BuildVerificationResult(success=not bad, feedback="undefined: missingEvaluationSymbol" if bad else "", synchronized_files=files)

    monkeypatch.setattr(MainLLMAgent, "refine_code", refine)
    monkeypatch.setattr("nl2service.build.verify.GoBuildVerifier.verify", verify)
    result = run_task(task(5))
    assert result["passed"], result
    assert [b["status"] for b in result["build_attempts"]] == ["failed", "passed"]
    assert diagnostics and "missingEvaluationSymbol" in diagnostics[0]
    assert result["repair_history"][0]["changed_files"] == ["handler/evaluation_fault.go"]
    assert workflow_metrics([result])["repair"]["compile_recovery"]["rate"] == 1


def test_final_behavior_failure_does_not_trigger_compiler_repair(monkeypatch):
    monkeypatch.setattr("nl2service.build.verify.GoBuildVerifier.verify", lambda self, files: BuildVerificationResult(success=True))
    monkeypatch.setattr("nl2service.evaluation.runner.run_behavior", lambda *args: {"status": "failed", "cases": [{"passed": False}]})
    result = run_task(task(0), execute_behavior=True)
    assert not result["passed"]
    assert result["failure_stage"] == "behavior"
    assert not any(s["node"] == "repair" for s in result["trace"])


def test_no_change_repair_stops_with_original_failure(monkeypatch):
    original = MainLLMAgent.refine_code
    def unchanged(self, session):
        if "handler/evaluation_fault.go" in session.rendered_files:
            return RefinementResult(files=dict(session.rendered_files), notes=[], model="controlled-test")
        return original(self, session)
    monkeypatch.setattr(MainLLMAgent, "refine_code", unchanged)
    monkeypatch.setattr("nl2service.build.verify.GoBuildVerifier.verify", lambda self, files: BuildVerificationResult(success=False, feedback="undefined: missingEvaluationSymbol", synchronized_files=files))
    result = run_task(task(5))
    assert not result["passed"]
    assert "no file changes" in result["error"]
    assert len(result["build_attempts"]) == 1


def test_workflow_metrics_distinguish_unreached_controls_and_natural_repair():
    base = {"passed": False, "trace": [], "checks": {}, "interrupts": [], "build_attempts": []}
    blocked = {**base, "category": "protocol_safety", "error": "No scripted response"}
    rejected = {**base, "passed": True, "category": "protocol_safety", "interrupts": ["proto", "proto"], "checks": {"invalid_proto_rejected": True}}
    repaired = {**base, "passed": True, "build_attempts": [{"status": "failed"}, {"status": "passed"}], "trace": [{"node": "repair"}], "behavior_case_count": 1, "behavior": {"status": "failed"}}
    m = workflow_metrics([blocked, rejected, repaired])
    assert m["protocol_rejection"]["trigger_coverage"]["rate"] == .5
    assert m["protocol_rejection"]["rejection_when_reached"]["rate"] == 1
    assert m["repair"]["natural_compile_recovery"]["rate"] == 1
    assert m["repair"]["synthetic_compile_recovery"]["rate"] is None
    assert m["repair"]["recovered_then_behavior_passed"]["rate"] == 0
    assert m["evaluation_blocked"]["missing_scripted_answers"] == 1


def test_no_failures_is_not_evidence_of_repair_effectiveness():
    m = workflow_metrics([])
    assert m["repair"]["compile_recovery"]["rate"] is None
    assert m["protocol_rejection"]["rejection_when_reached"]["rate"] is None
