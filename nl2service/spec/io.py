from __future__ import annotations

import json
from pathlib import Path

import yaml

from nl2service.spec.models import ServiceSpec


def load_spec_file(path: Path) -> ServiceSpec:
    raw = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(raw)
    else:
        data = yaml.safe_load(raw)
    return ServiceSpec.model_validate(data)


def dump_spec(spec: ServiceSpec) -> str:
    data = spec.model_dump(mode="json", exclude_none=True)
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def save_spec_file(spec: ServiceSpec, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_spec(spec), encoding="utf-8")
