"""Workflow evidence: distinguish eligibility, actual execution and outcome."""


def fraction(passed, total):
    return {"passed": passed, "total": total, "rate": passed / total if total else None}


def workflow_metrics(results):
    failed = [r for r in results if r.get("build_attempts") and r["build_attempts"][0]["status"] == "failed"]
    repaired = [r for r in failed if r["build_attempts"][-1]["status"] == "passed"]
    def recovery(rows):
        return fraction(sum(r["build_attempts"][-1]["status"] == "passed" for r in rows), len(rows))
    groups = {}
    for name, selected in (
        ("clarification", [r for r in results if r.get("category") == "clarification"]),
        ("requirement_update", [r for r in results if r.get("category") == "requirement_update"]),
        ("checkpoint_resume", [r for r in results if "checkpoint_restart" in r.get("checks", {})]),
        ("protocol_rejection", [r for r in results if r.get("category") == "protocol_safety"]),
    ):
        groups[name] = {"task_success": fraction(sum(r["passed"] for r in selected), len(selected))}
        if name == "protocol_rejection":
            reached = [r for r in selected if "proto" in r.get("interrupts", [])]
            groups[name].update(
                trigger_coverage=fraction(len(reached), len(selected)),
                rejection_when_reached=fraction(sum(r.get("checks", {}).get("invalid_proto_rejected", False) for r in reached), len(reached)))
        if name == "checkpoint_resume":
            groups[name]["restart_executed"] = fraction(sum(r.get("checkpoint_restarts", 0) > 0 for r in selected), len(selected))
    groups["repair"] = {
        "initial_build_failures": len(failed),
        "repair_entered": fraction(sum(any(s["node"] == "repair" for s in r.get("trace", [])) for r in failed), len(failed)),
        "compile_recovery": recovery(failed),
        "synthetic_compile_recovery": recovery([r for r in failed if r.get("fault_injected")]),
        "natural_compile_recovery": recovery([r for r in failed if not r.get("fault_injected")]),
        "recovered_then_behavior_passed": fraction(sum(r.get("behavior", {}).get("status") == "passed" for r in repaired if r.get("behavior_case_count", 0) > 0), sum(r.get("behavior_case_count", 0) > 0 for r in repaired)),
    }
    groups["evaluation_blocked"] = {
        "missing_scripted_answers": sum("No scripted response" in (r.get("error") or "") for r in results),
        "note": "Blocked trials remain failures in strict task success; protocol effectiveness is unavailable when its trigger was not reached.",
    }
    return groups
