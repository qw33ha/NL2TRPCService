import hashlib
import json
from pathlib import Path

from nl2service.build.verify import BuildVerificationResult
from nl2service.evaluation.runner import EvaluationVerifier, load_tasks, run_task


def tasks():
    return load_tasks(Path("nl2service/evaluation/tasks.jsonl"))


def test_frozen_eight_task_manifest():
    root = Path("nl2service/evaluation")
    manifest = json.loads((root / "benchmark-manifest.json").read_text())
    assert hashlib.sha256((root / "tasks.jsonl").read_bytes()).hexdigest() == manifest["dataset_sha256"]
    assert len(tasks()) == 8
    assert sum(task.split == "acceptance" for task in tasks()) == 2


def test_checkpoint_resume_preserves_user_correction(monkeypatch, tmp_path):
    monkeypatch.setattr("nl2service.build.verify.GoBuildVerifier.verify", lambda self, files: BuildVerificationResult(success=True))
    result = run_task(tasks()[4], artifacts=tmp_path)
    assert result["passed"], result
    assert result["checkpoint_restarts"] >= 2
    spec = json.loads((tmp_path / "requirement-update/evaluation-spec.json").read_text())
    assert spec["endpoints"][0]["path"] == "/ready"


def test_invalid_proto_reinterrupts_without_build(monkeypatch):
    def forbidden(*args):
        raise AssertionError("Invalid contract must not reach Go verification")
    monkeypatch.setattr("nl2service.build.verify.GoBuildVerifier.verify", forbidden)
    result = run_task(tasks()[7])
    assert result["passed"], result
    assert result["interrupts"].count("proto") == 2
    assert result["files"] == []


def test_fault_is_injected_once_and_persisted_for_repair(monkeypatch):
    def verify(self, files):
        bad = "missingEvaluationSymbol" in files.get("handler/evaluation_fault.go", "")
        return BuildVerificationResult(success=not bad, feedback="undefined symbol" if bad else "", synchronized_files=files)
    monkeypatch.setattr("nl2service.build.verify.GoBuildVerifier.verify", verify)
    verifier = EvaluationVerifier("undefined_symbol")
    initial = verifier.verify({"main.go": "package main"})
    assert not initial.success
    assert "handler/evaluation_fault.go" in initial.synchronized_files
    fixed = {**initial.synchronized_files, "handler/evaluation_fault.go": "package handler\n"}
    assert verifier.verify(fixed).success


def test_simplified_profile_has_no_ambiguity_model_or_llm_repair(monkeypatch):
    monkeypatch.setattr("nl2service.build.verify.GoBuildVerifier.verify", lambda self, files: BuildVerificationResult(success=False, feedback="unknown failure"))
    result = run_task(tasks()[0], profile="simplified")
    assert not result["passed"]
    assert "LLM repair is disabled" in result["error"]
    assert not any(step["node"] == "repair" for step in result["trace"])
