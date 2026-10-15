import pytest

from nl2service.spec.models import ServiceSpec
from nl2service.workflow.core import WorkflowCore
from nl2service.workflow.retrieval import HybridExampleSelector, bm25, cosine


class FakeEmbeddings:
    calls = input_tokens = hits = 0

    def embed(self, texts):
        self.calls += 1
        self.input_tokens += len(texts)
        return [[1.0, float("mysql" in text.lower())] for text in texts]


def test_bm25_exact_identifier_and_cosine():
    assert bm25("kafka", ["health http", "kafka producer"])[1] > 0
    assert bm25("kafka", ["health http", "kafka producer"])[0] == 0
    assert cosine([1, 0], [1, 0]) == 1
    with pytest.raises(ValueError):
        cosine([1], [1, 2])


def test_ir_excludes_disabled_dependency_and_preserves_evidence():
    selector = HybridExampleSelector(embeddings=FakeEmbeddings())
    bundle = selector.select(ServiceSpec(service={"mode": "http"}), "HTTP JSON handler")
    assert bundle.files
    assert all(name.startswith(("minimal-trpc-http-echo/", "retrieval-patterns/")) for name in bundle.files)
    assert selector.trace["embedding_calls"] == 1
    assert all(item["ir_compatible"] for item in selector.trace["selected"])
    assert all(item["rrf"] > 0 for item in selector.trace["selected"])
    assert selector.trace["corpus_sha256"]


def test_budget_and_no_retrieval():
    spec = ServiceSpec(service={"mode": "http"})
    assert HybridExampleSelector(mode="none").select(spec).files == {}
    selector = HybridExampleSelector(mode="bm25", max_characters=100)
    assert sum(map(len, selector.select(spec).files.values())) <= 100


def test_production_node_passes_references_and_trace():
    core = WorkflowCore()
    core.example_selector = HybridExampleSelector(embeddings=FakeEmbeddings())
    state = core._select_examples_node({"draft_spec": ServiceSpec(service={"mode": "http"}), "user_request": "HTTP health"})
    assert state["status"] == "examples_selected"
    assert state["example_reference_files"]
    assert state["retrieval_trace"]["mode"] == "ir-hybrid"


def test_embedding_failure_does_not_claim_hybrid_success():
    class Broken(FakeEmbeddings):
        def embed(self, texts):
            raise RuntimeError("private provider message")
    core = WorkflowCore()
    core.example_selector = HybridExampleSelector(embeddings=Broken())
    state = core._select_examples_node({"draft_spec": ServiceSpec(service={"mode": "http"})})
    assert state["status"] == "error"
    assert "private provider" not in state["error"]


def test_cache_response_indexes_and_skips_api(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import openai
    from nl2service.workflow.retrieval import CachedEmbeddings
    calls = []
    class Client:
        def __init__(self, **kwargs):
            self.embeddings = self
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(usage=SimpleNamespace(total_tokens=3), data=[
                SimpleNamespace(index=1, embedding=[0.0, 1.0]), SimpleNamespace(index=0, embedding=[1.0, 0.0])])
    monkeypatch.setattr(openai, "OpenAI", Client)
    cache = CachedEmbeddings(cache=tmp_path)
    assert cache.embed(["first", "second"]) == [[1.0, 0.0], [0.0, 1.0]]
    assert cache.embed(["second", "first"]) == [[0.0, 1.0], [1.0, 0.0]]
    assert len(calls) == 1 and cache.hits == 2
    assert not list(tmp_path.glob("*.tmp"))


def test_ablation_rejects_incomplete_or_mismatched_reports(tmp_path):
    import json
    from nl2service.evaluation.rag_compare import compare
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    first.write_text(json.dumps({"complete": False}))
    second.write_text(json.dumps({"complete": False}))
    with pytest.raises(ValueError, match="completed"):
        compare([first, second])
    first.write_text(json.dumps({"complete": True, "metadata": {"dataset_sha256": "a"}}))
    second.write_text(json.dumps({"complete": True, "metadata": {"dataset_sha256": "b"}}))
    with pytest.raises(ValueError, match="dataset"):
        compare([first, second])
