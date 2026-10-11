import json

import pytest
from pydantic import ValidationError

from nl2service.evaluation.judge import Criterion, Judgment, evidence_catalog, make_packet, summarize, validate_evidence
from nl2service.evaluation.runner import Task


def judgment(score=4, ref="E1"):
    value = {"score": score, "reason": "Matches evidence", "evidence": [{"evidence_id": ref}]}
    return Judgment(**{name: value for name in ("requirement_alignment", "clarification_quality", "spec_consistency")})


@pytest.mark.parametrize("score", [-1, 5, True, 2.5, "4"])
def test_judge_scores_are_bounded_strict_integers(score):
    with pytest.raises(ValidationError):
        judgment(score)


def test_numeric_judgment_requires_evidence():
    with pytest.raises(ValidationError):
        Criterion(score=4, reason="Trust me", evidence=[])


def test_evidence_must_be_copied_from_actual_named_source():
    with pytest.raises(ValueError, match="Ungrounded"):
        validate_evidence(judgment(ref="E999"), {"request": "health", "spec": {}, "dialogue": []})
    validate_evidence(judgment(), {"request": "health", "spec": {}, "dialogue": []})


def test_missing_spec_requires_abstention():
    with pytest.raises(ValueError, match="abstention"):
        validate_evidence(judgment(), {"request": "health", "spec": None})


def test_catalog_preserves_literal_strings_and_bounds_excerpt_size():
    packet = {"request": "x" * 1100, "dialogue": [], "spec": {"response": '{"status":"ok"}'}}
    catalog = evidence_catalog(packet)
    assert len({e["evidence_id"] for e in catalog}) == len(catalog)
    assert all(len(e["quote"]) <= 500 for e in catalog)
    assert any(e["quote"] == '{"status":"ok"}' and e["source"] == "spec" for e in catalog)


def test_packet_hides_profile_execution_scores_and_recovers_pending_question(tmp_path):
    task = Task(id="x", request="health", spec={})
    result = {"id": "x", "repeat": 1, "profile": "full", "passed": False, "behavior": {"passed": False},
              "dialogue": [], "error": "RuntimeError: No scripted response for interrupt: {'kind': 'clarification', 'question': 'What port?'}"}
    packet = make_packet(task, result, tmp_path)
    assert set(packet) == {"request", "spec", "dialogue", "dialogue_incomplete"}
    assert packet["spec"] is None
    assert packet["dialogue"][0]["interrupt"]["question"] == "What port?"
    assert packet["dialogue"][0]["response"] is None


def test_artifact_final_spec_takes_precedence_over_dataset_fixture(tmp_path):
    task = Task(id="x", request="health", spec={"old": True})
    path = tmp_path / "run-1/x/evaluation-spec.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"updated": True}))
    assert make_packet(task, {"id": "x", "repeat": 1}, tmp_path)["spec"] == {"updated": True}


def test_abstentions_and_invalid_judgments_do_not_become_passes():
    rows = [{"sample_id": "x", "judgment": judgment().model_dump()},
            {"sample_id": "x", "judgment": judgment(2).model_dump()}, {"sample_id": "y", "error": "bad JSON"}]
    m = summarize(rows)
    assert m["valid_judgments"] == {"passed": 2, "total": 3}
    assert m["criteria"]["requirement_alignment"]["mean_0_to_4"] == 3
    assert m["repeat_pass_fail_agreement"] == {"passed": 0, "total": 1}
    rows = [{"sample_id": "x", "judgment": judgment(None).model_dump()}] * 2
    m = summarize(rows)
    assert m["criteria"]["requirement_alignment"]["mean_0_to_4"] is None
    assert m["repeat_pass_fail_agreement"]["total"] == 0
