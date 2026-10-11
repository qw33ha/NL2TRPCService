"""Metric definitions shared by replay and live reports."""
import math
import statistics
from collections import Counter


def rate(passed, total):
    return {"passed": passed, "total": total, "rate": passed / total if total else None}


def summarize(results):
    durations = sorted(item["seconds"] for item in results)
    builds = [item for item in results if item.get("build_attempts")]
    behaviors = [case for item in results for case in item.get("behavior", {}).get("cases", [])]
    first = [item for item in results if item.get("build_attempts")]
    calls = [call for item in results for call in item.get("model_calls", [])]
    tokens = [call for call in calls if call.get("input_tokens") is not None]
    requested_cases = sum(item.get("behavior_case_count", len(item.get("behavior", {}).get("cases", []))) for item in results)
    first_behavior = [item["behavior_attempts"][0] for item in results if item.get("behavior_attempts")]
    recoverable = [item for item in results if item.get("behavior_attempts") and item["behavior_attempts"][0]["status"] == "failed"]
    metrics = {
        "task_success": rate(sum(item["passed"] for item in results), len(results)),
        "build_success_all_tasks": rate(sum(item["build_attempts"][-1].get("status") == "passed" for item in builds), len(results)),
        "build_success_attempted_tasks": rate(sum(item["build_attempts"][-1].get("status") == "passed" for item in builds), len(builds)),
        "first_build_success": rate(sum(item["build_attempts"][0].get("status") == "passed" for item in first), len(first)),
        "behavior_success": rate(sum(case["passed"] for case in behaviors), len(behaviors)),
        "behavior_success_all_requested_cases": rate(sum(case["passed"] for case in behaviors), requested_cases),
        "first_behavior_task_success": rate(sum(item["status"] == "passed" for item in first_behavior), len(first_behavior)),
        "behavior_repair_recovery": rate(sum(item.get("behavior", {}).get("status") == "passed" for item in recoverable), len(recoverable)),
        "behavior_task_coverage": rate(sum(bool(item.get("behavior", {}).get("cases")) for item in results), len(results)),
        "repair_node_calls": sum(sum(step["node"] == "repair" for step in item["trace"]) for item in results),
        "clarification_count": sum(item["interrupts"].count("clarification") for item in results),
        "deterministic_repairs": sum(sum(step.get("status") == "deterministic_repair_applied" for step in item["trace"]) for item in results),
        "failure_stages": dict(Counter(item.get("failure_stage", "unknown") for item in results if not item["passed"])),
        "latency_seconds": {"mean": statistics.mean(durations) if durations else None,
                            "median": statistics.median(durations) if durations else None,
                            "p95": durations[max(0, math.ceil(len(durations) * .95) - 1)] if durations else None,
                            "total": sum(durations)},
        "model_calls": len(calls),
        "token_usage": {"input": sum(call["input_tokens"] for call in tokens) if tokens else None,
                        "output": sum(call.get("output_tokens") or 0 for call in tokens) if tokens else None,
                        "calls_with_usage": len(tokens), "calls_total": len(calls)},
    }
    metrics["by_task"] = {
        task_id: {"success": rate(sum(item["passed"] for item in results if item["id"] == task_id), sum(item["id"] == task_id for item in results)),
                  "mean_seconds": statistics.mean(item["seconds"] for item in results if item["id"] == task_id)}
        for task_id in sorted({item.get("id", "unknown") for item in results})
    } if all("id" in item for item in results) else {}
    return metrics


def format_summary(report):
    metrics = report["metrics"]
    lines = ["NL2Service evaluation metrics", f"Mode: {report['metadata']['mode']}",
             f"Dataset SHA256: {report['metadata']['dataset_sha256']}",
             f"Repeated runs: {report['total']}; unique tasks: {len(metrics['by_task'])}"]
    for name in ("task_success", "build_success_all_tasks", "build_success_attempted_tasks", "first_build_success",
                 "behavior_success", "behavior_success_all_requested_cases", "behavior_task_coverage", "behavior_repair_recovery"):
        value = metrics[name]
        percentage = f"{value['rate']:.1%}" if value["rate"] is not None else "unavailable"
        lines.append(f"{name}: {value['passed']}/{value['total']} ({percentage})")
    lines.extend([f"Latency seconds: {metrics['latency_seconds']}",
                  f"Clarifications: {metrics['clarification_count']}; repair node calls: {metrics['repair_node_calls']}; deterministic repairs: {metrics['deterministic_repairs']}",
                  f"Model calls: {metrics['model_calls']}; token usage: {metrics['token_usage']}",
                  f"Failure stages: {metrics['failure_stages']}",
                  "Scope: three-task regression benchmark. Repeated runs are not independent production requests.",
                  "No USD cost estimate. Missing measurements are unavailable, not zero."])
    return "\n".join(lines) + "\n"
