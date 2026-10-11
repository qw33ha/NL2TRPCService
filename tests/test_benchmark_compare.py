from copy import deepcopy
import pytest

from nl2service.evaluation.compare import compare


def reports():
    common = {"complete": True, "metrics": {}, "metadata": {"dataset_sha256": "data", "source_sha256": "code",
              "model": "fixed", "mode": "live", "repeats": 1, "benchmark_version": "v2", "behavior_enabled": True,
              "split": "all", "scoring_feedback_to_model": False}}
    full, simple = deepcopy(common), deepcopy(common)
    full["metadata"]["profile"] = "full"
    simple["metadata"]["profile"] = "simplified"
    full["results"] = [{"id": "a", "repeat": 1, "passed": True}, {"id": "b", "repeat": 1, "passed": False}]
    simple["results"] = [{"id": "a", "repeat": 1, "passed": False}, {"id": "b", "repeat": 1, "passed": True}]
    return full, simple


def test_paired_outcomes_preserve_losses_as_well_as_wins():
    full, simple = reports()
    result = compare(full, simple)
    assert result["paired_outcomes"] == {"full_only": 1, "simplified_only": 1, "both_pass": 0, "both_fail": 0}


@pytest.mark.parametrize("change", ["dataset_sha256", "model", "source_sha256"])
def test_mismatched_runs_cannot_be_compared(change):
    full, simple = reports()
    simple["metadata"][change] = "different"
    with pytest.raises(ValueError, match="Mismatched"):
        compare(full, simple)


def test_incomplete_and_duplicate_runs_are_rejected():
    full, simple = reports()
    full["complete"] = False
    with pytest.raises(ValueError, match="complete"):
        compare(full, simple)
    full["complete"] = True
    full["results"].append(full["results"][0])
    with pytest.raises(ValueError, match="Duplicate"):
        compare(full, simple)
