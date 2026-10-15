from nl2service.spec.models import ServiceSpec
from nl2service.spec.constraints import constraint_tags
from nl2service.spec.validator import ServiceSpecValidator
from nl2service.workflow.retrieval import HybridExampleSelector


def contract():
    return ServiceSpec(service={"name": "contract", "module": "example.com/contract", "mode": "http"},
        repo={"owner": "example", "name": "contract"}, deploy={"enabled": False}, endpoints=[{
            "method": "POST", "path": "/compute", "input_fields": [
                {"name": "count", "type": "integer", "required": True, "minimum": 2, "maximum": 40}],
            "business_rules": [{"name": "scale", "expression": "floor(count / 7)", "operations": ["floor", "divide"]}],
            "validation_error_status": 422, "malformed_json_status": 400, "allow_unknown_fields": True}])


def test_constraint_ir_roundtrip_and_conflicting_bounds():
    spec = contract()
    assert ServiceSpec.model_validate_json(spec.model_dump_json()) == spec
    assert constraint_tags(spec) == {"integer", "required", "range", "floor", "divide", "validation_error", "malformed_json", "unknown_fields"}
    spec.endpoints[0].input_fields[0].minimum = 50
    errors = ServiceSpecValidator().validate(spec).issues
    assert any(e.field == "endpoints.0.input_fields.0.minimum" for e in errors)


def test_rpc_only_does_not_require_http_endpoint():
    spec = ServiceSpec(service={"mode": "rpc", "name": "rpc", "module": "example.com/rpc"},
        repo={"owner": "example", "name": "rpc"}, deploy={"enabled": False})
    assert not any(e.field == "endpoints" for e in ServiceSpecValidator().validate(spec).issues)
    spec.service.enable_http = True
    assert any(e.field == "endpoints" for e in ServiceSpecValidator().validate(spec).issues)


def test_constraint_reranking_moves_verified_patterns_ahead_of_capability_only(monkeypatch):
    from tests.test_hybrid_retrieval import FakeEmbeddings
    selector = HybridExampleSelector(embeddings=FakeEmbeddings(), top_k=3)
    bundle = selector.select(contract(), "HTTP compute integer business rule")
    assert set(bundle.files) == {"retrieval-patterns/json_validation.go#L1", "retrieval-patterns/integer_validation.go#L1", "retrieval-patterns/integer_arithmetic.go#L1"}
    assert selector.trace["constraint_tag_coverage"] == 1
    assert all(item["matched_constraint_tags"] for item in selector.trace["selected"])


def test_descriptive_formula_is_not_evaluated():
    spec = contract()
    spec.endpoints[0].business_rules[0].expression = "__import__('os').remove('important-file')"
    assert constraint_tags(spec) >= {"floor", "divide"}
    assert ServiceSpecValidator().validate(spec).issues == []
