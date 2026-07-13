from __future__ import annotations

from typing import Any

import yaml

from nl2service.spec.models import ServiceSpec


def apply_field_updates(spec: ServiceSpec, updates: dict[str, str]) -> ServiceSpec:
    data = spec.model_dump(mode="python")
    for field_path, raw_value in updates.items():
        _set_nested_value(data, field_path, _parse_value(raw_value))
    return ServiceSpec.model_validate(data)


def _parse_value(raw_value: str) -> Any:
    try:
        return yaml.safe_load(raw_value)
    except Exception:
        return raw_value


def _set_nested_value(data: dict[str, Any], field_path: str, value: Any) -> None:
    parts = field_path.split('.')
    cursor: Any = data
    for part in parts[:-1]:
        if part not in cursor or cursor[part] is None:
            cursor[part] = {}
        cursor = cursor[part]
    cursor[parts[-1]] = value
