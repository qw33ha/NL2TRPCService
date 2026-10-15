from nl2service.agent.ambiguity import SpecCorrection, apply_grounded_corrections
from nl2service.spec.models import ServiceSpec


def spec():
    return ServiceSpec(service={"mode": "http"}, endpoints=[{"path": "/x", "method": "POST", "allow_unknown_fields": False}])


def test_exact_quote_corrects_ir_and_records_evidence():
    item = SpecCorrection(field="endpoints.0.allow_unknown_fields", value=True, source_quote="Ignore unknown fields")
    corrected, evidence = apply_grounded_corrections(spec(), [item], "Ignore unknown fields.", [])
    assert corrected.endpoints[0].allow_unknown_fields is True
    assert evidence[0]["source_quote"] == "Ignore unknown fields"


def test_fabricated_quote_and_external_side_effect_fields_rejected():
    items = [SpecCorrection(field="endpoints.0.allow_unknown_fields", value=True, source_quote="Not in source"),
             SpecCorrection(field="deploy.enabled", value=True, source_quote="deploy now"),
             SpecCorrection(field="policy.store_plaintext_secrets", value=True, source_quote="deploy now")]
    original = spec()
    corrected, evidence = apply_grounded_corrections(original, items, "deploy now", [])
    assert corrected == original and evidence == []


def test_latest_answer_and_explicit_user_override_protected():
    item = SpecCorrection(field="endpoints.0.allow_unknown_fields", value=True, source_quote="Ignore unknown fields")
    original = spec()
    corrected, evidence = apply_grounded_corrections(original, [item], "Ignore unknown fields", [
        {"field": item.field, "answer": "Reject unknown fields instead"}])
    assert corrected == original and evidence == []
    corrected, evidence = apply_grounded_corrections(original, [item], "Ignore unknown fields", [], {item.field})
    assert corrected == original and evidence == []


def test_identifiers_must_be_literal_and_values_must_validate():
    items = [SpecCorrection(field="service.module", value="example.com/invented", source_quote="module unspecified"),
             SpecCorrection(field="endpoints.0.success_status", value=999, source_quote="return 999")]
    corrected, evidence = apply_grounded_corrections(spec(), items, "module unspecified; return 999", [])
    assert corrected == spec() and evidence == []


def test_grounded_correction_is_integrated_into_production_review_node(tmp_path):
    from nl2service.agent.ambiguity import AmbiguityReview, AmbiguityItem
    from nl2service.workflow.core import WorkflowCore
    from nl2service.workflow.conversation_graph import ConversationalServiceWorkflow
    from nl2service.runtime.checkpointer import SQLiteCheckpointRuntime
    class Provider:
        def get_model(self, name): return self
        def with_structured_output(self, *args, **kwargs): return self
        def invoke(self, messages):
            return AmbiguityReview(corrections=[SpecCorrection(field="endpoints.0.allow_unknown_fields", value=True,
                source_quote="Ignore unknown fields")], items=[AmbiguityItem(key="unknown", field="endpoints.0.allow_unknown_fields",
                question="Ignore them?", reason="Conflicting IR", impact="behavior", priority="blocking")])
    with SQLiteCheckpointRuntime(tmp_path / "state.db") as runtime:
        workflow = ConversationalServiceWorkflow(WorkflowCore(provider=Provider()), runtime.checkpointer)
        state = workflow._analyze_ambiguity_node({"draft_spec": spec(), "user_request": "Ignore unknown fields"})
    assert state["draft_spec"].endpoints[0].allow_unknown_fields is True
    assert state["ambiguity_items"] == [] and len(state["ir_corrections"]) == 1


def test_no_input_health_policy_does_not_hide_real_input_policy():
    from nl2service.agent.ambiguity import AmbiguityAnalyzer
    no_body = ServiceSpec(service={"mode": "http"}, endpoints=[{"path": "/status", "method": "GET"}])
    assert AmbiguityAnalyzer._irrelevant_input_policy(no_body, "endpoints.0.allow_unknown_fields")
    no_body.endpoints[0].request_description = "Accept query parameters for filtering"
    assert not AmbiguityAnalyzer._irrelevant_input_policy(no_body, "endpoints.0.allow_unknown_fields")


def test_literal_policy_is_scoped_and_user_revisions_win():
    from nl2service.agent.ambiguity import explicit_unknown_field_policy, AmbiguityAnalyzer
    original = spec()
    assert explicit_unknown_field_policy(original, "Ignore unknown input fields.", []) == (
        "endpoints.0.allow_unknown_fields", True, "Ignore unknown input fields")
    assert explicit_unknown_field_policy(original, "Ignore unknown input fields", [{"answer": "Reject unknown fields"}])[1] is False
    assert explicit_unknown_field_policy(original, "Do not ignore unknown fields", []) is None
    assert explicit_unknown_field_policy(original, "Do not accept arbitrary JSON", []) is None
    assert explicit_unknown_field_policy(original, "Reject arbitrary JSON", []) is None
    assert explicit_unknown_field_policy(original, "Ignore unknown fields; reject unknown fields", []) is None
    original.endpoints.append(original.endpoints[0].model_copy())
    assert explicit_unknown_field_policy(original, "Ignore unknown fields", []) is None
    original.endpoints[0].error_field = "error"
    assert AmbiguityAnalyzer._explicit_error_format(original, "endpoints.0.error_field", "All errors return exactly one string field error.")
    assert not AmbiguityAnalyzer._explicit_error_format(original, "endpoints.0.error_field", "All errors return one string field message.")
