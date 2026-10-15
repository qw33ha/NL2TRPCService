"""Conditional generation ablation: freeze an approved IR before varying retrieval."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

from langgraph.graph import StateGraph, START, END

from nl2service.evaluation.runner import load_tasks, UsageTracker, MeasuredProvider, BlockedDelivery, EvaluationVerifier
from nl2service.evaluation.behavior import run_behavior
from nl2service.evaluation.metrics import summarize
from nl2service.render.paths import safe_destination
from nl2service.runtime.checkpointer import SQLiteCheckpointRuntime
from nl2service.spec.models import ServiceSpec
from nl2service.spec.validator import ServiceSpecValidator
from nl2service.workflow.core import WorkflowCore
from nl2service.workflow.retrieval import HybridExampleSelector
from nl2service.workflow.state import WorkflowState, structured_state_defaults

MODES = ("none", "hybrid", "ir-hybrid")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def freeze(dataset: Path, source_report: Path, source_artifacts: Path):
    tasks = load_tasks(dataset)
    report = json.loads(source_report.read_text(encoding="utf-8"))
    dataset_hash = hashlib.sha256(dataset.read_bytes()).hexdigest()
    if not report.get("complete") or report["metadata"]["dataset_sha256"] != dataset_hash:
        raise ValueError("Require completed source report matching the frozen dataset.")
    prefixes, excluded = {}, []
    for task in tasks:
        if task.invalid_proto:
            excluded.append({"id": task.id, "reason": "Protocol rejection precedes generation; retained in full-workflow evaluation."})
            continue
        candidates = [r for r in report["results"] if r["id"] == task.id and r["repeat"] == 1]
        if len(candidates) != 1 or not any(step["node"] == "render_project" for step in candidates[0]["trace"]):
            raise ValueError(f"Missing approved generation prefix for {task.id}.")
        row = candidates[0]
        spec = ServiceSpec.model_validate_json((safe_destination(source_artifacts, task.id) / "evaluation-spec.json").read_text(encoding="utf-8"))
        if spec.service.enable_trpc or not spec.service.enable_http or spec.database.enabled or spec.kafka.enabled or spec.deploy.enabled is not False:
            raise ValueError("Paired execution requires isolated HTTP-only prefixes without external dependencies/deployment.")
        history, updates = [], []
        for turn in row.get("dialogue", []):
            event, response = turn["interrupt"], turn["response"]
            if event["kind"] == "clarification":
                history.append({"question": event["question"], "answer": str(response.get("answer", "")), "field": event.get("field")})
            if response.get("field_updates"):
                updates.append("Already approved requirement update: " + json.dumps(response["field_updates"], sort_keys=True))
        entry = {"spec": spec.model_dump(mode="json"), "user_request": task.request,
                 "clarification_history": history, "additional_context": updates}
        prefixes[task.id] = {**entry, "prefix_sha256": digest(entry)}
    return {"schema_version": 1, "scope": "Conditional on a fixed approved IR; upstream workflow success is not measured.",
            "dataset_sha256": dataset_hash, "source_report_sha256": hashlib.sha256(source_report.read_bytes()).hexdigest(),
            "source_revision": report["metadata"]["revision"], "prefixes": prefixes, "excluded": excluded}


def generation_graph(core, checkpointer):
    graph = StateGraph(WorkflowState)
    for name, method in [("render", core._render_project_node), ("retrieve", core._select_examples_node),
                         ("refine", core._refine_code_node), ("verify", core._verify_build_node), ("repair", core._repair_build_errors_node)]:
        graph.add_node(name, method)
    graph.add_node("contract_review", core._public_contract_review_node)
    graph.add_edge(START, "render")
    for source, target in [("render", "retrieve"), ("retrieve", "refine"), ("refine", "verify"), ("repair", "verify")]:
        graph.add_conditional_edges(source, lambda state, target=target: END if state.get("status") == "error" else target)
    def after_verify(state):
        if state.get("status") == "verified" and state.get("contract_review_required") and not state.get("contract_review_complete"):
            return "contract_review"
        return {"deterministic_repair_applied": "verify", "build_verification_failed": "repair"}.get(state.get("status"), END)
    graph.add_conditional_edges("verify", after_verify)
    graph.add_conditional_edges("contract_review", lambda state: "repair" if state.get("status") == "contract_review_requested" else END)
    return graph.compile(checkpointer=checkpointer)


def run_generation(task, prefix, mode, model, artifacts=None):
    if mode not in MODES:
        raise ValueError("Invalid paired retrieval mode.")
    original = {key: prefix[key] for key in ("spec", "user_request", "clarification_history", "additional_context")}
    if digest(original) != prefix["prefix_sha256"]:
        raise ValueError("Modified prefix.")
    spec = ServiceSpec.model_validate(prefix["spec"])
    if ServiceSpecValidator().validate(spec).issues:
        raise ValueError("Approved IR must pass deterministic validation.")
    started = time.monotonic()
    tracker, verifier = UsageTracker(), EvaluationVerifier(task.fault)
    core = WorkflowCore(model=model, provider=MeasuredProvider(tracker), github_provider=BlockedDelivery())
    core.example_selector = HybridExampleSelector(mode=mode)
    core.verifier = verifier
    trace, error, scaffold_hash = [], None, None
    behavior = {"status": "not_run", "cases": []}
    with TemporaryDirectory(prefix="nl2service-paired-") as directory:
        root = Path(directory)
        state = {**structured_state_defaults(), "draft_spec": spec, "user_request": prefix["user_request"],
                 "clarification_history": prefix["clarification_history"], "additional_context": prefix["additional_context"],
                 "model": model, "output_dir": str(root / "project"), "gate_confirmed": True, "target_phase": "verified"}
        with SQLiteCheckpointRuntime(root / "checkpoint.db") as runtime:
            graph = generation_graph(core, runtime.checkpointer)
            config = {"configurable": {"thread_id": task.id}, "recursion_limit": 40}
            try:
                for update in graph.stream(state, config, stream_mode="updates"):
                    for node, values in update.items():
                        trace.append({"node": node, "status": values.get("status")})
                        if node == "render":
                            scaffold_hash = digest(values.get("rendered_files", {}))
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
            final = graph.get_state(config).values
        if final.get("status") == "verified" and task.behavior_cases:
            behavior = run_behavior(root / "project", task.behavior_cases)
        if artifacts:
            destination = safe_destination(artifacts, task.id)
            core.renderer.write_tree(final.get("rendered_files", {}), destination)
    unchanged = final.get("draft_spec") is not None and digest(final["draft_spec"].model_dump(mode="json")) == digest(prefix["spec"])
    passed = final.get("status") == "verified" and not error and not final.get("error") and unchanged and behavior["status"] == "passed"
    return {"id": task.id, "category": task.category, "split": task.split, "mode": mode, "profile": "paired_generation", "passed": passed,
            "status": final.get("status"), "error": error or final.get("error"), "seconds": time.monotonic()-started,
            "prefix_sha256": prefix["prefix_sha256"], "scaffold_sha256": scaffold_hash, "ir_unchanged": unchanged,
            "trace": trace, "interrupts": [], "build_attempts": verifier.builds, "model_calls": tracker.calls,
            "behavior": behavior, "behavior_attempts": [behavior] if behavior["status"] != "not_run" else [],
            "behavior_case_count": len(task.behavior_cases), "fault_injected": verifier.fault_injected,
            "retrieval_trace": final.get("retrieval_trace", {}), "repair_history": final.get("repair_history", []),
            "failure_stage": None if passed else ("behavior" if behavior["status"] == "failed" else "generation_or_build")}


def paired_summary(results):
    groups = {mode: [r for r in results if r["mode"] == mode] for mode in MODES}
    pairs = {}
    for mode in MODES[1:]:
        base = {(r["id"], r["repeat"]): r for r in groups["none"]}
        other = {(r["id"], r["repeat"]): r for r in groups[mode]}
        if len(base) != len(groups["none"]) or len(other) != len(groups[mode]):
            raise ValueError("Duplicate task/repeat pairs.")
        counts = {key: 0 for key in ("both_pass", "baseline_only", "retrieval_only", "both_fail")}
        for key in base.keys() & other.keys():
            left, right = base[key], other[key]
            if left["prefix_sha256"] != right["prefix_sha256"] or left["scaffold_sha256"] != right["scaffold_sha256"]:
                raise ValueError("Paired IR/scaffold mismatch.")
            counts["both_pass" if left["passed"] and right["passed"] else "baseline_only" if left["passed"] else "retrieval_only" if right["passed"] else "both_fail"] += 1
        pairs[mode] = counts
    return {"metrics": {mode: summarize(rows, grouped=False) for mode, rows in groups.items()}, "pairs": pairs}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path(__file__).with_name("tasks.jsonl"))
    sub = parser.add_subparsers(dest="command", required=True)
    freezer = sub.add_parser("freeze")
    freezer.add_argument("--source-report", type=Path, required=True)
    freezer.add_argument("--source-artifacts", type=Path, required=True, help="Source run-1 directory")
    freezer.add_argument("--output", type=Path, required=True)
    run = sub.add_parser("run")
    run.add_argument("--prefixes", type=Path, required=True)
    run.add_argument("--report", type=Path, required=True)
    run.add_argument("--artifacts", type=Path, required=True)
    run.add_argument("--repeats", type=int, default=3)
    run.add_argument("--model", default="gpt-4.1-mini-2025-04-14")
    args = parser.parse_args()
    if args.command == "freeze":
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(freeze(args.dataset, args.source_report, args.source_artifacts), indent=2), encoding="utf-8")
        return
    if args.repeats < 1:
        parser.error("Repeats must be positive.")
    manifest = json.loads(args.prefixes.read_text(encoding="utf-8"))
    if manifest["dataset_sha256"] != hashlib.sha256(args.dataset.read_bytes()).hexdigest():
        raise ValueError("Prefix/dataset mismatch.")
    tasks = [task for task in load_tasks(args.dataset) if task.id in manifest["prefixes"]]
    if not tasks:
        raise ValueError("No generation tasks.")
    results = []
    revision = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    source_digest = hashlib.sha256()
    for path in sorted(Path(__file__).parents[1].rglob("*")):
        if path.is_file() and path.suffix in {".py", ".tpl", ".jsonl"}:
            source_digest.update(path.relative_to(Path(__file__).parents[1]).as_posix().encode())
            source_digest.update(path.read_bytes())
    def save(complete):
        report = {"complete": complete, "scope": manifest["scope"], "revision": revision, "model": args.model,
                  "prefix_manifest_sha256": hashlib.sha256(args.prefixes.read_bytes()).hexdigest(), "excluded": manifest["excluded"],
                  "source_sha256": source_digest.hexdigest(), "upstream_calls_replayed": True,
                  "planned_total": len(tasks)*len(MODES)*args.repeats, "results": results, **paired_summary(results)}
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    save(False)
    with ThreadPoolExecutor(max_workers=3) as executor:
        for repeat in range(1, args.repeats+1):
            for task in tasks:
                order = MODES[repeat % 3:] + MODES[:repeat % 3]
                futures = [(mode, executor.submit(run_generation, task, manifest["prefixes"][task.id], mode, args.model,
                            args.artifacts / mode / f"run-{repeat}")) for mode in order]
                for mode, future in futures:
                    result = future.result()
                    result["repeat"] = repeat
                    results.append(result)
                    save(False)
                    print(f"{task.id} repeat={repeat} mode={mode} passed={result['passed']}", flush=True)
    save(True)


if __name__ == "__main__":
    main()
