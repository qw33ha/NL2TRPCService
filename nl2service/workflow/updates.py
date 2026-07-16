from __future__ import annotations

from typing import Any

import yaml

from nl2service.spec.models import ServiceSpec


def apply_field_updates(spec: ServiceSpec, updates: dict[str, Any]) -> ServiceSpec:
    data = spec.model_dump(mode="python")
    for field_path, raw_value in updates.items():
        value = _parse_value(raw_value) if isinstance(raw_value, str) else raw_value
        _set_nested_value(data, field_path, value)
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
        if isinstance(cursor, list):
            try:
                index = int(part)
            except ValueError as exc:
                raise ValueError(f"Expected a numeric list index in field path {field_path!r}, got {part!r}.") from exc
            if index < 0 or index >= len(cursor):
                raise ValueError(f"List index {index} is out of range in field path {field_path!r}.")
            cursor = cursor[index]
            continue
        if not isinstance(cursor, dict):
            raise ValueError(f"Cannot traverse {part!r} in field path {field_path!r}.")
        if part not in cursor or cursor[part] is None:
            cursor[part] = {}
        cursor = cursor[part]

    final = parts[-1]
    if isinstance(cursor, list):
        try:
            index = int(final)
        except ValueError as exc:
            raise ValueError(f"Expected a numeric list index in field path {field_path!r}, got {final!r}.") from exc
        if index < 0 or index >= len(cursor):
            raise ValueError(f"List index {index} is out of range in field path {field_path!r}.")
        cursor[index] = value
        return
    if not isinstance(cursor, dict):
        raise ValueError(f"Cannot set {final!r} in field path {field_path!r}.")
    cursor[final] = value
