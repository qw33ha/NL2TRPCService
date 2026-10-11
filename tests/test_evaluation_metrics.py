from nl2service.evaluation.metrics import summarize


def test_metrics_distinguish_unattempted_builds_and_behavior():
    common = {"seconds": 2, "trace": [], "interrupts": [], "model_calls": []}
    results = [
        {**common, "passed": True, "local_build": {"status": "passed"},
         "build_attempts": [{"status": "failed"}, {"status": "passed"}],
         "behavior": {"cases": [{"passed": True}, {"passed": False}]}},
        {**common, "passed": False, "local_build": None, "build_attempts": [],
         "interrupts": ["clarification"], "behavior": {"cases": []}},
    ]
    metrics = summarize(results)
    assert metrics["task_success"]["rate"] == .5
    assert metrics["build_success_all_tasks"]["rate"] == .5
    assert metrics["build_success_attempted_tasks"]["rate"] == 1
    assert metrics["first_build_success"]["rate"] == 0
    assert metrics["behavior_success"]["rate"] == .5
    assert metrics["behavior_task_coverage"]["rate"] == .5
    assert metrics["token_usage"]["input"] is None


def test_empty_metrics_are_unavailable_not_perfect():
    metrics = summarize([])
    assert metrics["task_success"]["rate"] is None
    assert metrics["latency_seconds"]["p95"] is None
