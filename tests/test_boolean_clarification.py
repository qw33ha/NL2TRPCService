import pytest
from pydantic import ValidationError

from nl2service.spec.models import ServiceSpec
from nl2service.workflow.updates import apply_field_updates


def test_boolean_explanation_is_typed_without_corrupting_strings():
    spec = ServiceSpec(service={"mode": "http"}, endpoints=[{"path": "/x", "method": "POST"}])
    updated = apply_field_updates(spec, {"deploy.enabled": "False; deployment disabled.",
        "endpoints.0.allow_unknown_fields": "True. Ignore extra fields.", "repo.name": "False; literal repository name"})
    assert updated.deploy.enabled is False
    assert updated.endpoints[0].allow_unknown_fields is True
    assert updated.repo.name == "False; literal repository name"


def test_uncertain_boolean_is_not_guessed():
    with pytest.raises(ValidationError):
        apply_field_updates(ServiceSpec(), {"deploy.enabled": "Maybe; ask later"})
