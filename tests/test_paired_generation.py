import pytest
from langgraph.checkpoint.memory import MemorySaver
from nl2service.evaluation.paired import generation_graph, paired_summary, digest


def test_failed_refinement_stops_paired_graph_before_verification():
    calls = []
    class Core:
        def _render_project_node(self, state): return {"status": "rendered"}
        def _select_examples_node(self, state): return {"status": "examples_selected"}
        def _refine_code_node(self, state): return {"status": "error", "error": "model failure"}
        def _verify_build_node(self, state):
            calls.append("verify")
            return {"status": "verified"}
        def _repair_build_errors_node(self, state): raise AssertionError("unexpected repair")
        def _public_contract_review_node(self, state): raise AssertionError("unexpected review")
    final = generation_graph(Core(), MemorySaver()).invoke({}, {"configurable": {"thread_id": "x"}})
    assert final["status"] == "error" and not calls


def test_fixed_prefix_and_scaffold_are_required_for_paired_comparison():
    def row(mode, passed):
        return {"id": "x", "repeat": 1, "mode": mode, "passed": passed, "seconds": 1,
                "trace": [], "interrupts": [], "prefix_sha256": "prefix", "scaffold_sha256": "scaffold"}
    base, retrieval = row("none", False), row("hybrid", True)
    assert paired_summary([base, retrieval])["pairs"]["hybrid"]["retrieval_only"] == 1
    retrieval["prefix_sha256"] = "different"
    with pytest.raises(ValueError, match="mismatch"):
        paired_summary([base, retrieval])
    retrieval["prefix_sha256"] = "prefix"
    with pytest.raises(ValueError, match="Duplicate"):
        paired_summary([base, base, retrieval])


def test_digest_is_order_independent_but_detects_constraint_changes():
    assert digest({"minimum": 2, "type": "integer"}) == digest({"type": "integer", "minimum": 2})
    assert digest({"minimum": 2}) != digest({"minimum": 3})
