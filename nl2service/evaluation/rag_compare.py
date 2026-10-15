"""Compare completed matched retrieval ablations without hiding workflow failures."""
import argparse
import json
from pathlib import Path


def compare(paths):
    reports = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    if len(reports) < 2 or any(not report.get("complete") for report in reports):
        raise ValueError("Need at least two completed reports.")
    for key in ["dataset_sha256", "source_sha256", "model", "profile", "behavior_enabled"]:
        if len({str(report["metadata"].get(key)) for report in reports}) != 1:
            raise ValueError(f"Unmatched {key}.")
    pairs = [{(r["id"], r["repeat"]) for r in report["results"]} for report in reports]
    if any(pair != pairs[0] for pair in pairs):
        raise ValueError("Unmatched task/repeat pairs.")
    modes = [report["metadata"]["retrieval_mode"] for report in reports]
    if len(set(modes)) != len(modes):
        raise ValueError("Duplicate retrieval modes.")
    rows = {}
    for mode, report in zip(modes, reports):
        results = report["results"]
        rows[mode] = {"passed": report["passed"], "total": report["total"], "metrics": report["metrics"],
                      "retrieval_reached": sum(bool(r.get("retrieval_trace")) for r in results),
                      "embedding_calls": sum(r.get("retrieval_trace", {}).get("embedding_calls", 0) for r in results),
                      "embedding_input_tokens": sum(r.get("retrieval_trace", {}).get("embedding_tokens", 0) for r in results),
                      "ir_input_fields": sum(len(e.get("input_fields", [])) for r in results for e in r.get("constraint_ir", [])),
                      "ir_business_rules": sum(len(e.get("business_rules", [])) for r in results for e in r.get("constraint_ir", [])),
                      "constraint_tag_coverage_mean": (
                          sum(r["retrieval_trace"]["constraint_tag_coverage"] for r in results if r.get("retrieval_trace", {}).get("constraint_tag_coverage") is not None)
                          / sum(r.get("retrieval_trace", {}).get("constraint_tag_coverage") is not None for r in results)
                          if any(r.get("retrieval_trace", {}).get("constraint_tag_coverage") is not None for r in results) else None),
                      "failure_stages": {stage: sum(r.get("failure_stage") == stage for r in results)
                                         for stage in ["clarification", "behavior", "build", "workflow"]}}
    return {"scope": "Matched task/repeat pilot. One repeat cannot establish statistical significance; blocked cases remain failures.",
            "metadata": reports[0]["metadata"], "modes": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = compare(args.reports)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print({mode: {k: v for k, v in row.items() if k != "metrics"} for mode, row in result["modes"].items()})
