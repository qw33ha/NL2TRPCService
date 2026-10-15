from __future__ import annotations

import hashlib
import json
from pathlib import Path

from nl2service.workflow.examples import ExampleBundle
from nl2service.workflow.retrieval import bm25, cosine, CachedEmbeddings

ROOT = Path(__file__).parent


class OfficialKnowledgeSelector:
    """Retrieve capability bundles with API, usage and config provenance together."""
    def __init__(self, mode="official-rag", max_characters=28000, embeddings=None):
        if mode not in {"official-rag", "official-full-context", "official-none"}:
            raise ValueError("Invalid official knowledge mode.")
        self.mode, self.max_characters = mode, max_characters
        self.embeddings = embeddings or CachedEmbeddings()
        self.trace = {}

    def select(self, spec, request=""):
        manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        capabilities = {"trpc"}
        if spec.database.enabled and spec.database.type == "mysql":
            capabilities.add("mysql")
        if spec.redis.enabled:
            capabilities.add("redis")
        if spec.kafka.enabled:
            capabilities.add("kafka")
        bundles = [bundle for bundle in manifest["bundles"] if bundle["capability"] in capabilities]
        by_id = {bundle["id"]: i for i, bundle in enumerate(bundles)}
        def closure(indices):
            indices = tuple(indices)
            included = set(indices)
            pending = list(indices)
            while pending:
                index = pending.pop()
                for dependency in bundles[index].get("requires", []):
                    if dependency not in by_id:
                        raise ValueError(f"Missing capability dependency: {dependency}")
                    child = by_id[dependency]
                    if child not in included:
                        included.add(child)
                        pending.append(child)
            available = {symbol for i in included for symbol in bundles[i].get("provides_symbols", [])}
            missing = {symbol for i in included for symbol in bundles[i].get("requires_symbols", [])} - available
            if missing:
                raise ValueError(f"Missing API type dependencies: {sorted(missing)}")
            return included
        closure(range(len(bundles)))
        texts = []
        entries = {entry["local_path"]: entry for bundle in bundles for entry in bundle["entries"]}
        for bundle in bundles:
            content = []
            for item in bundle["entries"]:
                path = ROOT / item["local_path"]
                source = path.read_text(encoding="utf-8")
                if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
                    raise ValueError("Pinned knowledge content changed.")
                content.append(f"SOURCE {item['url']}\nVERSION {item['version']} LICENSE {item['license']}\n"
                               f"SYMBOLS {item['symbols']} IMPORT {item['import_path']} CONFIG_KEYS {item['config_keys']}\n{source}")
            for note in bundle.get("semantic_links", []):
                evidence=[]
                for citation in note["evidence"]:
                    entry=entries[citation["local_path"]]
                    raw=(ROOT/entry["local_path"]).read_bytes()
                    if hashlib.sha256(raw).hexdigest()!=entry["sha256"] or citation["quote"] not in raw.decode("utf-8"):
                        raise ValueError("Ungrounded API semantic link.")
                    evidence.append(entry["url"] + "\n" + citation["quote"])
                content.append("DERIVED API INTERPRETATION (verify against cited pinned source):\n"+note["claim"]+"\nEVIDENCE\n"+"\n".join(evidence))
            texts.append("\n\n".join(content))
        query = request + "\n" + spec.model_dump_json(exclude_none=True)
        selected = list(range(len(bundles)))
        before = self.embeddings.calls, self.embeddings.input_tokens, getattr(self.embeddings,"hits",0)
        scores = [0.0]*len(bundles)
        if self.mode == "official-none":
            selected = []
        elif self.mode == "official-rag":
            sparse = bm25(query, texts)
            vectors = self.embeddings.embed(texts + [query])
            dense = [cosine(vector, vectors[-1]) for vector in vectors[:-1]]
            for values in (sparse, dense):
                order = sorted(range(len(bundles)), key=lambda i: (-values[i], bundles[i]["id"]))
                for rank, index in enumerate(order, 1):
                    scores[index] += 1/(60+rank)
            ranked = sorted(selected, key=lambda i: (-scores[i], bundles[i]["id"]))
            needed = set(capabilities)
            if spec.kafka.enabled and spec.kafka.group:
                needed.add('kafka.consumer')
            if spec.database.enabled and spec.database.type == "mysql" and spec.database.transaction_requirements:
                needed.add("mysql.transactions")
            required = closure(i for i, bundle in enumerate(bundles) if needed.intersection(bundle.get("required_for", [])))
            chosen = set(required)
            for index in ranked:
                if len(chosen) >= 2:
                    break
                chosen = closure(chosen | {index})
            selected = [i for i in ranked if i in chosen]
        files, used, ids = {}, 0, []
        for index in selected:
            if used + len(texts[index]) > self.max_characters:
                raise ValueError("Knowledge context budget exceeded; do not silently truncate capability evidence.")
            bundle = bundles[index]
            files["official/" + bundle["id"]] = texts[index]
            ids.append(bundle["id"])
            used += len(texts[index])
        self.trace = {"mode": self.mode, "manifest_sha256": hashlib.sha256((ROOT / "manifest.json").read_bytes()).hexdigest(),
                      "selected_bundles": ids, "reference_characters": used, "max_characters": self.max_characters,
                      "scores": {bundles[i]["id"]: scores[i] for i in selected},
                      "dependency_closed": True,
                      "embedding_model":getattr(self.embeddings,"model","fixture"),
                      "embedding_cache_hits":getattr(self.embeddings,"hits",0)-before[2],
                      "embedding_calls": self.embeddings.calls-before[0], "embedding_tokens": self.embeddings.input_tokens-before[1]}
        return ExampleBundle(ids, files)
