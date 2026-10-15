"""Auditable BM25/dense retrieval over trusted repository examples, never eval answers."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from nl2service.spec.models import ServiceSpec
from nl2service.spec.constraints import constraint_tags
from nl2service.workflow.examples import EXAMPLE_CATALOG, ExampleBundle, ExampleSelector


def tokens(text: str) -> list[str]:
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    return re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", text.lower())


def bm25(query: str, documents: list[str]) -> list[float]:
    counts = [Counter(tokens(text)) for text in documents]
    average = sum(map(lambda c: sum(c.values()), counts)) / max(1, len(counts))
    scores = [0.0] * len(counts)
    for term in set(tokens(query)):
        frequency = sum(term in count for count in counts)
        idf = math.log(1 + (len(counts) - frequency + 0.5) / (frequency + 0.5))
        for index, count in enumerate(counts):
            tf = count[term]
            if tf:
                scores[index] += idf * tf * 2.5 / (tf + 1.5 * (0.25 + 0.75 * sum(count.values()) / max(average, 1)))
    return scores


def cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        raise ValueError("Embedding dimensions must match and be nonempty.")
    norm = math.sqrt(sum(x*x for x in left) * sum(x*x for x in right))
    if not norm or not all(math.isfinite(x) for x in left + right):
        raise ValueError("Embeddings must be finite and nonzero.")
    return sum(x*y for x, y in zip(left, right)) / norm


class CachedEmbeddings:
    def __init__(self, cache: Path | None = None, model: str = "text-embedding-3-small"):
        self.model = model
        self.cache = cache or Path.home() / ".cache/nl2service/embeddings"
        self.calls = self.input_tokens = self.hits = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        from openai import OpenAI
        self.cache.mkdir(parents=True, exist_ok=True)
        namespace = (os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1") + "\0" + self.model
        paths = [self.cache / (hashlib.sha256((namespace + "\0" + text).encode()).hexdigest() + ".json") for text in texts]
        values = [json.loads(path.read_text()) if path.exists() else None for path in paths]
        missing = [i for i, value in enumerate(values) if value is None]
        self.hits += len(texts) - len(missing)
        if missing:
            client = OpenAI(base_url=os.getenv("OPENAI_BASE_URL") or None)
            response = client.embeddings.create(model=self.model, input=[texts[i] for i in missing])
            self.calls += 1
            self.input_tokens += response.usage.total_tokens
            if len(response.data) != len(missing):
                raise ValueError("Incomplete embedding response.")
            if sorted(item.index for item in response.data) != list(range(len(missing))):
                raise ValueError("Invalid embedding response indexes.")
            for item in response.data:
                index = missing[item.index]
                cosine(item.embedding, item.embedding)
                values[index] = item.embedding
                temporary = paths[index].with_suffix(f".{uuid.uuid4().hex}.tmp")
                temporary.write_text(json.dumps(item.embedding), encoding="utf-8")
                temporary.replace(paths[index])
        return values


@dataclass(frozen=True)
class Chunk:
    id: str
    capability: str
    content: str
    constraint_tags: frozenset[str] = frozenset()


class HybridExampleSelector(ExampleSelector):
    """RRF fuses both rankings; explicit transport/dependency IR rules rerank candidates."""
    MODES = {"none", "legacy", "bm25", "dense", "hybrid", "ir-hybrid"}

    def __init__(self, mode="ir-hybrid", embeddings=None, top_k=6, **kwargs):
        super().__init__(**kwargs)
        if mode not in self.MODES or top_k < 1:
            raise ValueError("Invalid retrieval mode or top_k.")
        self.mode, self.top_k = mode, top_k
        self.embeddings = embeddings or CachedEmbeddings()
        self.trace = {}

    def corpus(self) -> list[Chunk]:
        result = []
        for example in EXAMPLE_CATALOG:
            for name in example.files:
                path = self.examples_root / example.directory / name
                if path.is_file():
                    content = path.read_text(encoding="utf-8")
                    # Bounded line chunks retain source identity and avoid whole-file embedding limits.
                    lines = content.splitlines(keepends=True)
                    for start in range(0, len(lines), 60):
                        result.append(Chunk(f"{example.name}/{name}#L{start+1}", example.capability, "".join(lines[start:start+60])))
        patterns = {
            "json_validation.go": {"malformed_json", "validation_error", "unknown_fields", "object"},
            "integer_validation.go": {"integer", "required", "range", "validation_error"},
            "integer_arithmetic.go": {"multiply", "divide", "floor"},
        }
        for name, tags in patterns.items():
            path = Path(__file__).parents[1] / "knowledge" / "patterns" / name
            if path.is_file():
                result.append(Chunk(f"retrieval-patterns/{name}#L1", "http", path.read_text(encoding="utf-8"), frozenset(tags)))
        return result

    def select(self, spec: ServiceSpec, request: str = "") -> ExampleBundle:
        self.trace = {"mode": self.mode}
        if self.mode == "none":
            return ExampleBundle([], {})
        if self.mode == "legacy":
            return super().select(spec)
        chunks = self.corpus()
        if not chunks:
            raise ValueError("Retrieval corpus is empty.")
        # Only approved spec and request enter query. Deployment credentials/metadata are excluded.
        ir = {"transport": spec.service.mode, "endpoints": [e.model_dump() for e in spec.endpoints],
              "database": spec.database.type if spec.database.enabled else None, "kafka": spec.kafka.enabled}
        query = request + "\n" + json.dumps(ir, ensure_ascii=False)
        texts = [c.id + "\n" + c.capability + "\n" + " ".join(sorted(c.constraint_tags)) + "\n" + c.content for c in chunks]
        sparse = bm25(query, texts)
        dense = [0.0] * len(chunks)
        before = (self.embeddings.calls, self.embeddings.input_tokens, self.embeddings.hits)
        if self.mode in {"dense", "hybrid", "ir-hybrid"}:
            vectors = self.embeddings.embed(texts + [query])
            dense = [cosine(vector, vectors[-1]) for vector in vectors[:-1]]
        rankings = []
        if self.mode != "dense":
            rankings.append(sorted(range(len(chunks)), key=lambda i: (-sparse[i], chunks[i].id)))
        if self.mode != "bm25":
            rankings.append(sorted(range(len(chunks)), key=lambda i: (-dense[i], chunks[i].id)))
        fused = [0.0] * len(chunks)
        for ranking in rankings:
            for rank, index in enumerate(ranking, 1):
                fused[index] += 1 / (60 + rank)
        candidates = sorted(range(len(chunks)), key=lambda i: (-fused[i], chunks[i].id))[:max(12, self.top_k * 3)]
        capabilities = self._capabilities(spec)
        required_tags = constraint_tags(spec)
        def matches(index):
            return required_tags & chunks[index].constraint_tags
        def compatible(index):
            return chunks[index].capability in capabilities
        # Hard dependency mismatches outrank relevance: never inject disabled MySQL/Kafka references.
        if self.mode == "ir-hybrid":
            candidates.sort(key=lambda i: (not compatible(i), -len(matches(i)), -fused[i], chunks[i].id))
            candidates = [i for i in candidates if compatible(i)]
        files, selected, used = {}, [], 0
        for i in candidates:
            if len(files) >= self.top_k:
                break
            chunk = chunks[i]
            if used + len(chunk.content) > self.max_characters:
                continue
            files[chunk.id] = chunk.content
            used += len(chunk.content)
            selected.append(i)
        self.trace.update(ir=ir, corpus_sha256=hashlib.sha256("\n".join(texts).encode()).hexdigest(),
            query_sha256=hashlib.sha256(query.encode()).hexdigest(),
            embedding_model=getattr(self.embeddings, "model", "fixture"), fusion="reciprocal_rank_k60",
            reranker="dependency_then_constraint_tag_overlap_then_rrf_v2" if self.mode == "ir-hybrid" else "none",
            requested_constraint_tags=sorted(required_tags),
            covered_constraint_tags=sorted(set().union(*(matches(i) for i in selected))),
            constraint_tag_coverage=(len(set().union(*(matches(i) for i in selected))) / len(required_tags)) if required_tags else None,
            corpus_chunks=len(chunks), selected=[{"id": chunks[i].id, "bm25": sparse[i], "cosine": dense[i],
            "rrf": fused[i], "ir_compatible": compatible(i), "matched_constraint_tags": sorted(matches(i))} for i in selected], reference_characters=used,
            embedding_calls=self.embeddings.calls-before[0], embedding_tokens=self.embeddings.input_tokens-before[1],
            cache_hits=self.embeddings.hits-before[2])
        return ExampleBundle(sorted({chunks[i].id.split("/")[0] for i in selected}), files)
