from __future__ import annotations

from copy import deepcopy
from typing import Any

from nl2service.spec.defaults import (
    DEFAULT_EXPOSURE_TYPE,
    DEFAULT_HEALTH_PATH,
    DEFAULT_KUBECONFIG_SECRET,
    DEFAULT_REPLICAS,
    DEFAULT_RUNTIME,
)
from nl2service.spec.models import ServiceSpec


class ServiceSpecNormalizer:
    """Normalize LLM-produced specs back onto platform-owned defaults and invariants."""

    def normalize(self, spec: ServiceSpec) -> ServiceSpec:
        data = deepcopy(spec.model_dump(mode="python"))
        cleaned = self._clean_value(data)
        self._apply_platform_defaults(cleaned)
        return ServiceSpec.model_validate(cleaned)

    def _clean_value(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {key: self._clean_value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._clean_value(item) for item in value]
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    def _apply_platform_defaults(self, data: dict[str, Any]) -> None:
        service = data.setdefault("service", {})
        service["runtime"] = DEFAULT_RUNTIME

        deploy = data.setdefault("deploy", {})
        deploy["replicas"] = deploy.get("replicas") or DEFAULT_REPLICAS
        deploy["kubeconfig_secret"] = deploy.get("kubeconfig_secret") or DEFAULT_KUBECONFIG_SECRET

        exposure = data.setdefault("exposure", {})
        exposure["type"] = exposure.get("type") or DEFAULT_EXPOSURE_TYPE
        exposure["health_path"] = exposure.get("health_path") or DEFAULT_HEALTH_PATH

        policy = data.setdefault("policy", {})
        policy["require_gate"] = True
        policy["store_plaintext_secrets"] = False
        policy["allow_load_balancer"] = exposure.get("type") == "loadBalancer"

        repo = data.setdefault("repo", {})
        repo["owner"] = repo.get("owner") or None
        repo["name"] = repo.get("name") or None

        kafka = data.setdefault("kafka", {})
        kafka["brokers"] = kafka.get("brokers") or []
