"""Small development retrieval diagnostic; labels describe capabilities, not correctness."""
import argparse
import json
from pathlib import Path

from nl2service.spec.models import ServiceSpec
from nl2service.workflow.retrieval import CachedEmbeddings, HybridExampleSelector


QUERIES = [
    ("http-json", "HTTP JSON health and echo request response", None, False, "http"),
    ("http-method", "HTTP unsupported request method JSON error response", None, False, "http"),
    ("mysql-query", "persistent user records SQL database MySQL query", "mysql", False, "mysql"),
    ("mysql-pool", "MySQL connection pool database configuration", "mysql", False, "mysql"),
    ("kafka-producer", "send events to Kafka topic producer", None, True, "kafka"),
    ("kafka-security", "Kafka TLS SASL authentication producer configuration", None, True, "kafka"),
]


def evaluate(embeddings=None):
    embeddings = embeddings or CachedEmbeddings()
    scores = {}
    for mode in ["bm25", "dense", "hybrid", "ir-hybrid"]:
        rows = []
        for name, query, database, kafka, label in QUERIES:
            spec = ServiceSpec(service={"mode": "http"}, database={"enabled": bool(database), "type": database}, kafka={"enabled": kafka})
            selector = HybridExampleSelector(mode=mode, embeddings=embeddings, top_k=3)
            selector.select(spec, query)
            relevant = {chunk.id for chunk in selector.corpus() if chunk.capability == label}
            retrieved = [item["id"] for item in selector.trace["selected"]]
            hits = [item in relevant for item in retrieved]
            rows.append({"id": name, "query": query, "relevant_ids": sorted(relevant),
                         "precision_at_3": sum(hits)/3, "recall_at_3": sum(hits)/len(relevant),
                         "reciprocal_rank": next((1/(i+1) for i, hit in enumerate(hits) if hit), 0),
                         "trace": selector.trace})
        scores[mode] = {"precision_at_3": sum(row["precision_at_3"] for row in rows)/len(rows),
                        "recall_at_3": sum(row["recall_at_3"] for row in rows)/len(rows),
                        "mrr_at_3": sum(row["reciprocal_rank"] for row in rows)/len(rows), "results": rows}
    return {"scope": "Six development diagnostics; capability labels, not code correctness or held-out generalization.",
            "embedding_model": embeddings.model if hasattr(embeddings, "model") else "fixture",
            "embedding_calls": embeddings.calls, "embedding_input_tokens": embeddings.input_tokens, "modes": scores}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print({mode: {key: value for key, value in metrics.items() if key != "results"} for mode, metrics in report["modes"].items()})


if __name__ == "__main__":
    main()
