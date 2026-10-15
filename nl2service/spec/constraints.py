"""Explicit constraint projection shared by retrieval and evidence reporting."""
from nl2service.spec.models import ServiceSpec


def constraint_tags(spec: ServiceSpec) -> set[str]:
    tags = set()
    for endpoint in spec.endpoints:
        for field in endpoint.input_fields:
            tags.add(field.type)
            if field.required:
                tags.add("required")
            if field.minimum is not None or field.maximum is not None:
                tags.add("range")
        if endpoint.malformed_json_status is not None:
            tags.add("malformed_json")
        if endpoint.validation_error_status is not None:
            tags.add("validation_error")
        if endpoint.allow_unknown_fields is True:
            tags.add("unknown_fields")
        for rule in endpoint.business_rules:
            tags.update(rule.operations)
    return tags
