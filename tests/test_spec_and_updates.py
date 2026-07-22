from __future__ import annotations

import pytest
from pydantic import ValidationError

from nl2service.spec.models import ServiceSpec
from nl2service.spec.validator import ServiceSpecValidator
from nl2service.workflow.updates import apply_field_updates


@pytest.mark.parametrize(
    ("mode", "trpc", "http"),
    [
        ("http", False, True),
        ("rpc", True, False),
        ("hybrid", True, True),
    ],
)
def test_transport_modes_are_normalized(mode: str, trpc: bool, http: bool) -> None:
    spec = ServiceSpec.model_validate({"service": {"mode": mode}})

    assert spec.service.enable_trpc is trpc
    assert spec.service.enable_http is http


def test_nested_and_list_updates_preserve_other_values(http_spec: ServiceSpec) -> None:
    spec = apply_field_updates(
        http_spec,
        {
            "database.enabled": "true",
            "database.type": "mysql",
            "database.host": "db.example.internal",
            "database.port": "3301",
            "endpoints.0.path": "/v2/events",
        },
    )

    assert spec.database.enabled is True
    assert spec.database.type == "mysql"
    assert spec.database.host == "db.example.internal"
    assert spec.database.port == 3301
    assert spec.endpoints[0].path == "/v2/events"
    assert spec.service.name == "regression-service"


def test_whole_database_object_cannot_be_replaced_by_boolean(http_spec: ServiceSpec) -> None:
    with pytest.raises(ValidationError):
        apply_field_updates(http_spec, {"database": True})


def test_deployment_can_be_explicitly_skipped(http_spec: ServiceSpec) -> None:
    result = ServiceSpecValidator().validate(http_spec)

    deploy_errors = [issue for issue in result.issues if issue.field.startswith("deploy.")]
    assert deploy_errors == []
