"""Compare paired, complete runs without changing task results."""
import argparse
import json
from pathlib import Path


def compare(full, simplified):
    if not full.get("complete") or not simplified.get("complete"):
        raise ValueError("Both reports must be complete")
    for key in ("dataset_sha256", "source_sha256", "model", "mode", "repeats", "benchmark_version", "behavior_enabled", "split"):
        if full["metadata"].get(key) != simplified["metadata"].get(key):
            raise ValueError(f"Mismatched comparison metadata: {key}")
    if full["metadata"].get("profile") != "full" or simplified["metadata"].get("profile") != "simplified":
        raise ValueError("Expected full and simplified profiles")
    if any(report["metadata"].get("scoring_feedback_to_model") for report in (full, simplified)):
        raise ValueError("Final scoring assertions must not be repair feedback")
    def indexed(report):
        index = {(item["id"], item["repeat"]): item for item in report["results"]}
        if len(index) != len(report["results"]):
            raise ValueError("Duplicate trial keys")
        return index
    left, right = indexed(full), indexed(simplified)
    if left.keys() != right.keys():
        raise ValueError("Task/repeat pairs differ")
    outcomes = {"full_only": 0, "simplified_only": 0, "both_pass": 0, "both_fail": 0}
    for key in left:
        a, b = left[key]["passed"], right[key]["passed"]
        outcomes["both_pass" if a and b else "full_only" if a else "simplified_only" if b else "both_fail"] += 1
    return {"benchmark_version": full["metadata"]["benchmark_version"],
            "dataset_sha256": full["metadata"]["dataset_sha256"], "model": full["metadata"]["model"],
            "paired_trials": len(left), "paired_outcomes": outcomes,
            "full": full["metrics"], "simplified": simplified["metrics"],
            "notes": ["Simplified shares the model, scaffold, schema clarification and deterministic repairs; removes ambiguity LLM, examples and LLM repair.",
                      "Final scoring assertions are withheld from both generation and repair.",
                      "Acceptance results were not used to tune generation during this benchmark version.",
                      "The compiler-recovery task uses a declared synthetic fault and is reported separately.",
                      "Profiles ran concurrently on one local machine; latency is descriptive, not an isolated speed benchmark.",
                      "This comparison does not isolate the contribution of individual removed components."]}


def render(comparison):
    lines = [f"NL2Service {comparison['benchmark_version']}: full vs simplified", f"Model: {comparison['model']}",
             f"Paired trials: {comparison['paired_trials']}; outcomes: {comparison['paired_outcomes']}"]
    for label, metrics in (("FULL", comparison["full"]), ("SIMPLIFIED", comparison["simplified"])):
        lines.append("\n" + label)
        for key in ("task_success", "build_success_all_tasks", "first_build_success", "behavior_success_all_requested_cases", "behavior_task_coverage", "injected_compile_recovery"):
            value = metrics[key]
            lines.append(f"{key}: {value['passed']}/{value['total']}")
        for split, values in metrics["by_split"].items():
            value = values["task_success"]
            lines.append(f"{split}: {value['passed']}/{value['total']}")
        lines.extend([f"Latency: {metrics['latency_seconds']}", f"Model calls: {metrics['model_calls']}; tokens: {metrics['token_usage']}",
                      f"Clarifications: {metrics['clarification_count']}; repair calls: {metrics['repair_node_calls']}"])
        for task, values in metrics["by_task"].items():
            value = values["success"]
            lines.append(f"  {task}: {value['passed']}/{value['total']}")
    lines.append("\n" + "\n".join(comparison["notes"]))
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", type=Path, required=True)
    parser.add_argument("--simplified", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = compare(json.loads(args.full.read_text(encoding="utf-8")), json.loads(args.simplified.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    args.output.with_suffix(".txt").write_text(render(result), encoding="utf-8")
    print(f"Saved comparison: {args.output}")


if __name__ == "__main__":
    main()
