"""Locked MySQL composition evaluation with official-RAG/full-context/no-RAG controls."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import subprocess
import time
from pathlib import Path

from nl2service.evaluation.mysql_runtime import MySQLRuntime, RPCService, IMAGE
from nl2service.evaluation.paired import generation_graph, digest
from nl2service.evaluation.runner import UsageTracker, MeasuredProvider, BlockedDelivery, EvaluationVerifier
from nl2service.knowledge.official import OfficialKnowledgeSelector
from nl2service.render.official_mysql import OfficialMySQLRenderer, PROTO
from nl2service.runtime.checkpointer import SQLiteCheckpointRuntime
from nl2service.spec.models import ServiceSpec
from nl2service.workflow.core import WorkflowCore
from nl2service.workflow.state import structured_state_defaults
from nl2service.evaluation.costs import summarize_cost, PRICING_PATH

MODES = ("official-none", "official-full-context", "official-rag")


class BudgetProvider(MeasuredProvider):
    def get_model(self, name):
        model = super().get_model(name)
        model.max_tokens = 8192
        return model


def public_spec(task):
    return ServiceSpec(service={"name": task["id"], "module": "example.com/"+task["id"], "mode": "rpc", "proto_file": str(PROTO)},
        database={"enabled": True, "type": "mysql", "database": "nl2bench", "host": "127.0.0.1", "port": 3306,
                  "table": task["tables"][0]["name"], "secret_name": "ephemeral-test-env", "tables": task["tables"],
                  "transaction_requirements": task["transaction_requirements"]},
        repo={"owner": "example", "name": task["id"]}, deploy={"enabled": False})


def generation_request(task):
    # Deliberately not serializing private setup SQL or private cases.
    return ("Generate the variable MySQL implementation for the fixed official tRPC wire scaffold. "
        "Implement storageService.Execute(context.Context,json.RawMessage) (json.RawMessage,error) in service.go. "
        "storageService.db is the official trpc-database/mysql Client. Do not redefine storageService or change main/go.mod/YAML. "
        "Dispatch by JSON op, return JSON domain responses and nil Go error for documented domain errors; unexpected infrastructure "
        "errors should return a non-nil Go error unless the requirement explicitly defines db_error. Never hardcode data, credentials, "
        "or maintain records in process memory. Use the supplied table schema and real parameterized SQL. " + task["request"])


def evaluate_cases(service, database, cases):
    """Observe database state even when the RPC response itself fails."""
    assertions = []
    for index, case in enumerate(cases):
        actual, sql_actual, errors = None, None, {}
        checks = {"rpc_response": False}
        try:
            if case.get("restart"):
                service.restart()
            actual = service.call(case["payload"])
            checks["rpc_response"] = actual == case["expected"]
        except Exception as exc:
            errors["rpc"] = str(exc).replace(database.password, "[redacted]")
        if case.get("sql"):
            checks["independent_database_state"] = False
            try:
                sql_actual = database.sql(case["sql"])
                checks["independent_database_state"] = sql_actual == case["sql_expected"]
            except Exception as exc:
                errors["sql"] = str(exc).replace(database.password, "[redacted]")
        assertions.append({"index": index, "passed": all(checks.values()), "checks": checks,
                           "actual": actual, "independent_sql": sql_actual, "errors": errors,
                           "service_restart": case.get("restart", False)})
    return assertions


def run_task(task, mode, model, artifacts, database):
    spec = public_spec(task)
    root = artifacts / mode / task["id"]
    root.mkdir(parents=True, exist_ok=True)
    tracker = UsageTracker()
    core = WorkflowCore(provider=BudgetProvider(tracker), model=model, github_provider=BlockedDelivery())
    core.contract_review_enabled = False
    core.renderer = OfficialMySQLRenderer()
    core.example_selector = OfficialKnowledgeSelector(mode)
    verifier = EvaluationVerifier()
    core.verifier = verifier
    request = generation_request(task)
    state = {**structured_state_defaults(), "draft_spec": spec, "user_request": request, "model": model,
             "output_dir": str(root), "gate_confirmed": True, "target_phase": "verified", "additional_context": [], "clarification_history": []}
    started = time.monotonic()
    trace, error, scaffold_hash = [], None, None
    with SQLiteCheckpointRuntime(root / "checkpoint.db") as runtime:
        graph = generation_graph(core, runtime.checkpointer)
        config = {"configurable": {"thread_id": task["id"]}, "recursion_limit": 40}
        try:
            for update in graph.stream(state, config, stream_mode="updates"):
                for node, values in update.items():
                    trace.append({"node": node, "status": values.get("status")})
                    if node == "render":
                        scaffold_hash = digest(values.get("rendered_files", {}))
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        final = graph.get_state(config).values
    assertions = []
    if final.get("status") == "verified":
        tables = [table["name"] for table in task["tables"]]
        if any(not re.fullmatch(r"[a-zA-Z_]\w*", name) for name in tables):
            raise ValueError("Unsafe benchmark table identifier.")
        database.sql("SET FOREIGN_KEY_CHECKS=0;" + "".join(f"DROP TABLE IF EXISTS `{name}`;" for name in tables) + "SET FOREIGN_KEY_CHECKS=1;")
        database.sql(task["private_setup_sql"])
        try:
            with RPCService(root, database) as service:
                assertions = evaluate_cases(service, database, task["private_cases"])
        except Exception as exc:
            error = str(exc).replace(database.password,"[redacted]")
    passed = bool(assertions) and len(assertions) == len(task["private_cases"]) and all(row["passed"] for row in assertions) and not error
    return {"id": task["id"], "mode": mode, "passed": passed, "status": final.get("status"), "error": error or final.get("error"),
            "public_ir_sha256": digest(spec.model_dump(mode="json")), "public_request_sha256": digest(request), "scaffold_sha256": scaffold_hash,
            "seconds": time.monotonic()-started, "model_calls": tracker.calls, "build_attempts": verifier.builds,
            "retrieval": final.get("retrieval_trace", {}), "assertions": assertions, "planned_assertions": len(task["private_cases"]),
            "repair_history": final.get("repair_history", []), "trace": trace, "final_scoring_feedback_to_model": False}


def summary(results):
    metrics = {}
    for mode in MODES:
        rows = [row for row in results if row["mode"] == mode]
        calls = [call for row in rows for call in row["model_calls"]]
        metrics[mode] = {"task_passed": sum(row["passed"] for row in rows), "tasks": len(rows),
            "assertions_passed": sum(case["passed"] for row in rows for case in row["assertions"]),
            "assertions_planned": sum(row["planned_assertions"] for row in rows),
            "model_calls": len(calls), "input_tokens": sum(call.get("input_tokens") or 0 for call in calls),
            "output_tokens": sum(call.get("output_tokens") or 0 for call in calls)}
        metrics[mode]['cost']=summarize_cost(rows)
    return metrics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--model", default="gpt-4.1-2025-04-14")
    parser.add_argument("--modes", nargs="+", choices=MODES, default=list(MODES))
    parser.add_argument("--dataset", type=Path, default=Path(__file__).with_name("mysql-composition-tasks.jsonl"))
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    dataset = args.dataset
    manifest = args.manifest or (dataset.with_name("mysql-composition-manifest.json") if dataset.name=="mysql-composition-tasks.jsonl" else dataset.with_suffix(".manifest.json"))
    lock = json.loads(manifest.read_text())
    if hashlib.sha256(dataset.read_bytes()).hexdigest() != lock["dataset_sha256"]:
        raise ValueError("Locked composition tasks changed.")
    tasks = [json.loads(line) for line in dataset.read_text().splitlines()]
    results = []
    metadata = {"dataset_sha256": lock["dataset_sha256"], "knowledge_manifest_sha256": hashlib.sha256((Path(__file__).parents[1]/"knowledge/manifest.json").read_bytes()).hexdigest(),
                "revision": subprocess.run(["git","rev-parse","HEAD"],capture_output=True,text=True).stdout.strip(),
                "model": args.model, "context_character_budget": 28000, "max_output_tokens": 8192, "max_repairs": 3,
                "modes":args.modes,"contract_review":False,
                "pricing_sha256":hashlib.sha256(PRICING_PATH.read_bytes()).hexdigest(),
                "mysql_image": IMAGE, "repeats": 1,
                "dataset_status": lock.get("dataset_status","developer-observed regression tasks; not held-out"),
                "scope": "Frozen within each run; actual protobuf tRPC and disposable MySQL. Corpus/prompt development across earlier runs is documented separately."}
    def save(complete):
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps({"complete":complete,"planned_total":len(tasks)*len(args.modes),"metadata":metadata,"results":results,"metrics":summary(results)},indent=2),encoding="utf-8")
    save(False)
    with MySQLRuntime() as database:
        for index, task in enumerate(tasks):
            modes=tuple(args.modes)
            order = modes[index%len(modes):] + modes[:index%len(modes)]
            for mode in order:
                print(f"Generating {task['id']} mode={mode}",flush=True)
                result = run_task(task,mode,args.model,args.artifacts,database)
                results.append(result);save(False)
                print(f"  passed={result['passed']} assertions={sum(c['passed'] for c in result['assertions'])}/{result['planned_assertions']}",flush=True)
    save(True)


if __name__ == "__main__":
    main()
