from __future__ import annotations

import argparse
import json
import time
import uuid
import hashlib
import platform
from importlib.metadata import version
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from langgraph.types import Command
from pydantic import BaseModel, Field
from langchain_core.callbacks import BaseCallbackHandler

from nl2service.agent.provider import LLMProvider
from nl2service.runtime.checkpointer import SQLiteCheckpointRuntime
from nl2service.spec.models import ServiceSpec
from nl2service.workflow.conversation_graph import ConversationalServiceWorkflow
from nl2service.workflow.core import WorkflowCore
from nl2service.evaluation.behavior import run_behavior
from nl2service.evaluation.metrics import summarize, format_summary
from nl2service.build.verify import GoBuildVerifier, BuildVerificationResult


class Task(BaseModel):
    id: str
    request: str
    spec: dict
    responses: list[dict] = Field(default_factory=list)
    expected_status: str = "verified"
    required_files: list[str] = Field(default_factory=lambda: ["main.go", "go.mod"])
    behavior_cases: list[dict] = Field(default_factory=list)
    clarification_answers: dict[str, str] = Field(default_factory=dict)


class BlockedDelivery:
    """Never instantiate the credential-bearing GitHub client in evaluations."""

    def __getattr__(self, name):
        raise RuntimeError(f"Evaluation forbids external delivery: {name}")


class ReplayProvider:
    """Replay structured model responses; all workflow nodes remain production code."""

    def __init__(self, spec):
        self.spec = spec

    def get_model(self, name):
        return self

    def with_structured_output(self, schema, **kwargs):
        provider = self

        class Response:
            def invoke(self, messages):
                if schema is ServiceSpec:
                    return schema.model_validate(provider.spec)
                if schema.__name__ == "RefinedRender":
                    return schema(files={"handler/evaluation_test.go": HTTP_SMOKE_TEST})
                return schema()

        return Response()


HTTP_SMOKE_TEST = '''package handler

import (
    "net/http"
    "net/http/httptest"
    "testing"
)

func TestEvaluationHTTP(t *testing.T) {
    h := NewHTTPHandler()
    server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        if err := h.Health(w, r); err != nil { t.Error(err) }
    }))
    defer server.Close()
    response, err := http.Get(server.URL + "/health")
    if err != nil { t.Fatal(err) }
    defer response.Body.Close()
    if response.StatusCode != 200 { t.Fatalf("status: %d", response.StatusCode) }
    if response.Header.Get("Content-Type") != "application/json" { t.Fatal("missing JSON content type") }
}
'''


def load_tasks(path: Path) -> list[Task]:
    tasks = [Task.model_validate(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    ids = [task.id for task in tasks]
    if len(ids) != len(set(ids)):
        raise ValueError("Task IDs must be unique")
    return tasks


class UsageTracker(BaseCallbackHandler):
    def __init__(self):
        self.calls = []
        self.started = {}

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        self.started[run_id] = time.monotonic()

    def on_llm_end(self, response, **kwargs):
        usage = (response.llm_output or {}).get("token_usage", {})
        for generations in response.generations:
            for generation in generations:
                metadata = getattr(getattr(generation, "message", None), "usage_metadata", None)
                if metadata:
                    usage = {"prompt_tokens": metadata.get("input_tokens"), "completion_tokens": metadata.get("output_tokens")}
                    break
        self.calls.append({"input_tokens": usage.get("prompt_tokens"), "output_tokens": usage.get("completion_tokens"),
                           "model": (response.llm_output or {}).get("model_name"),
                           "seconds": round(time.monotonic() - self.started.pop(kwargs.get("run_id"), time.monotonic()), 3)})

    def on_llm_error(self, error, **kwargs):
        self.calls.append({"input_tokens": None, "output_tokens": None, "error": type(error).__name__})


class MeasuredProvider(LLMProvider):
    def __init__(self, tracker):
        super().__init__()
        self.tracker = tracker

    def get_model(self, name):
        model = super().get_model(name)
        model.callbacks = [self.tracker]
        return model


class EvaluationVerifier:
    """Feed executable behavior failures through the production repair loop."""
    def __init__(self, cases):
        self.cases = cases
        self.builds = []
        self.behaviors = []

    def verify(self, files):
        result = GoBuildVerifier().verify(files)
        self.builds.append({"status": "passed" if result.success else "failed", "command": result.command})
        if not result.success:
            return result
        with TemporaryDirectory(prefix="nl2service-behavior-") as directory:
            root = Path(directory)
            from nl2service.render.renderer import ServiceRenderer
            ServiceRenderer().write_tree(result.synchronized_files or files, root)
            behavior = run_behavior(root, self.cases)
        self.behaviors.append(behavior)
        if behavior["status"] == "failed":
            diagnostic = ""
            if any("http.HandleFunc(" in content and "thttp.HandleFunc(" not in content for path, content in files.items() if path.endswith(".go")):
                diagnostic = ("\nRouter diagnosis: net/http.HandleFunc registers on the standard library mux, which the tRPC-Go http_no_protocol server does not use. "
                              "Register each path with thttp.HandleFunc(path, h.Method), where thttp imports trpc.group/trpc-go/trpc-go/http "
                              "and h.Method has signature func(http.ResponseWriter, *http.Request) error. Remove the standard-library wrapper/router registration.\n")
            return BuildVerificationResult(success=False, command="evaluation HTTP behavior", exit_code=1,
                feedback="The complete generated server failed executable HTTP evaluation. Repair the implementation, preserve the tRPC-Go configured server entrypoint, and satisfy these fixed assertions:\n" + json.dumps(behavior) + diagnostic,
                synchronized_files=result.synchronized_files)
        return result


def run_task(task: Task, *, live: bool = False, execute_behavior: bool = False, artifacts: Path | None = None) -> dict:
    started = time.monotonic()
    trace = []
    interrupts = []
    result = {}
    error = None
    tracker = UsageTracker()
    builds = []
    behavior = {"status": "not_run", "cases": []}
    with TemporaryDirectory(prefix="nl2service-eval-") as directory:
        root = Path(directory)
        core = WorkflowCore(provider=MeasuredProvider(tracker) if live else ReplayProvider(task.spec), github_provider=BlockedDelivery())
        evaluator = EvaluationVerifier(task.behavior_cases) if execute_behavior and task.behavior_cases else None
        if evaluator:
            core.verifier = evaluator
        with SQLiteCheckpointRuntime(root / "checkpoint.db") as runtime:
            graph = ConversationalServiceWorkflow(core, runtime.checkpointer).graph
            config = {"configurable": {"thread_id": str(uuid.uuid4())}, "recursion_limit": 80}
            payload = {"user_request": task.request, "output_dir": str(root / "project"), "github_delivery": {}}
            responses = iter(task.responses)
            try:
                for _ in range(20):
                    for update in graph.stream(payload, config, stream_mode="updates"):
                        for node, state in update.items():
                            if node != "__interrupt__":
                                trace.append({"node": node, "status": state.get("status")})
                                if node == "verify_build":
                                    builds.append(dict(state.get("local_build", {})))
                    snapshot = graph.get_state(config)
                    result = snapshot.values
                    pending = [item for item in snapshot.tasks for item in item.interrupts]
                    if not pending:
                        break
                    kind = pending[0].value.get("kind")
                    interrupts.append(kind)
                    if kind == "github_approval":
                        response = {"confirmed": False}
                    elif kind == "approval":
                        response = {"confirmed": True}
                    elif kind in {"clarification", "proto"}:
                        field = pending[0].value.get("field")
                        if field in task.clarification_answers:
                            response = {"answer": task.clarification_answers[field]}
                        else:
                            try:
                                response = next(responses)
                            except StopIteration as exc:
                                raise RuntimeError(f"No scripted response for interrupt: {pending[0].value}") from exc
                        expected_field = response.get("field")
                        if expected_field and expected_field != pending[0].value.get("field"):
                            raise RuntimeError(f"Expected clarification for {expected_field}, got {pending[0].value}")
                    else:
                        raise RuntimeError(f"Forbidden evaluation interrupt: {kind}")
                    payload = Command(resume=response)
                else:
                    raise RuntimeError("Evaluation exceeded interrupt budget")
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                result = graph.get_state(config).values
            if evaluator:
                builds = evaluator.builds
                if evaluator.behaviors:
                    behavior = evaluator.behaviors[-1]
            if artifacts:
                from nl2service.render.paths import safe_destination
                destination = safe_destination(artifacts, task.id)
                core.renderer.write_tree(result.get("rendered_files", {}), destination)
                spec = result.get("draft_spec")
                if spec:
                    (destination / "evaluation-spec.json").write_text(spec.model_dump_json(indent=2), encoding="utf-8")
    files = result.get("rendered_files", {})
    checks = {
        "expected_status": result.get("status") == task.expected_status,
        "required_files": all(path in files for path in task.required_files),
        "no_delivery": not result.get("github_delivery") and not any(item["node"] == "deliver_to_github" for item in trace),
        "no_error": not error and not result.get("error"),
    }
    if execute_behavior and task.behavior_cases:
        checks["behavior"] = behavior["status"] == "passed"
    failure_stage = None
    if not all(checks.values()):
        if error and "interrupt" in error:
            failure_stage = "clarification"
        elif behavior["status"] == "failed":
            failure_stage = "behavior"
        elif builds and builds[-1].get("status") == "failed":
            failure_stage = "build"
        else:
            failure_stage = "workflow"
    return {"id": task.id, "mode": "live" if live else "replay", "passed": all(checks.values()), "checks": checks,
            "status": result.get("status"), "error": error or result.get("error"), "seconds": round(time.monotonic() - started, 3),
            "trace": trace, "interrupts": interrupts, "local_build": result.get("local_build"), "files": sorted(files),
            "build_attempts": builds, "behavior": behavior, "model_calls": tracker.calls,
            "behavior_attempts": evaluator.behaviors if evaluator else [], "behavior_case_count": len(task.behavior_cases),
            "failure_stage": failure_stage}


def main():
    parser = argparse.ArgumentParser(description="Evaluate the production LangGraph without GitHub delivery")
    parser.add_argument("--dataset", type=Path, default=Path(__file__).with_name("tasks.jsonl"))
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--live", action="store_true", help="Use configured LLM credentials instead of deterministic replay")
    parser.add_argument("--artifacts", type=Path, help="Retain generated source for review")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--skip-behavior", action="store_true", help="Report compile-only results")
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be at least 1")
    dataset_bytes = args.dataset.read_bytes()
    source_root = Path(__file__).parents[1]
    digest = hashlib.sha256()
    for path in sorted(source_root.rglob("*")):
        if path.is_file() and path.suffix in {".py", ".tpl", ".j2", ".jsonl"}:
            digest.update(path.relative_to(source_root).as_posix().encode())
            digest.update(path.read_bytes())
    source_sha256 = digest.hexdigest()
    tasks = load_tasks(args.dataset)
    results = []
    for repeat in range(args.repeats):
        for task in tasks:
            print(f"Running {task.id} (repeat {repeat + 1})", flush=True)
            result = run_task(task, live=args.live, execute_behavior=not args.skip_behavior,
                              artifacts=args.artifacts / f"run-{repeat + 1}" if args.artifacts else None)
            result["repeat"] = repeat + 1
            results.append(result)
            print(f"  passed={result['passed']}; status={result['status']}; behavior={result['behavior']['status']}", flush=True)
            if result["error"]:
                print(f"  error={result['error']}", flush=True)
    revision = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    report = {"schema_version": 2, "passed": sum(item["passed"] for item in results), "total": len(results), "results": results,
              "metrics": summarize(results), "metadata": {"timestamp_utc": datetime.now(timezone.utc).isoformat(),
              "revision": revision, "working_tree_dirty": bool(subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True).stdout.strip()),
              "python": platform.python_version(), "mode": "live" if args.live else "replay",
              "dataset_sha256": hashlib.sha256(dataset_bytes).hexdigest(), "repeats": args.repeats,
              "source_sha256": source_sha256,
              "dependencies": {name: version(name) for name in ("langgraph", "langchain-openai", "pydantic")},
              "go": subprocess.run(["go", "version"], capture_output=True, text=True).stdout.strip()}}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    args.report.with_suffix(".txt").write_text(format_summary(report), encoding="utf-8")
    print(f"{report['passed']}/{report['total']} passed; report: {args.report}")
    raise SystemExit(0 if results and all(item["passed"] for item in results) else 1)
