from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner
import typer

from nl2service.cli import _read_message
from nl2service.agent.runtime import AgentSession
from nl2service.agent.conversation import ClarificationInterpreter, ConversationDecision, ConversationUpdate
from nl2service.workflow.updates import apply_field_updates
from nl2service.agent.events import AgentEvent


def test_multiline_paste_is_one_message():
    app = typer.Typer()
    messages = []

    @app.command()
    def read():
        messages.extend([_read_message(), _read_message()])

    result = CliRunner().invoke(app, input='/paste\nEach item requires:\n- product_id: string\n\n- quantity: integer\n/end\nyes\n')
    assert result.exit_code == 0
    assert messages == ['Each item requires:\n- product_id: string\n\n- quantity: integer', 'yes']


@pytest.mark.parametrize('kind', ['approval', 'github_approval', 'clarification'])
def test_bad_model_update_keeps_user_at_pending_gate(http_spec, kind):
    session = AgentSession.__new__(AgentSession)
    decision = ConversationDecision(intent='correct', updates=[
        ConversationUpdate(field='endpoints.0.input_fields.3', value_json='{"name":"product_id","type":"string"}'),
    ])
    session.clarification_interpreter = SimpleNamespace(
        route_turn=Mock(return_value=decision),
        route_confirmation=Mock(return_value=decision),
        _normalize=lambda field, value: value,
    )
    before = http_spec.model_dump()
    reply = session._interpret_reply({'kind': kind}, 'Add product_id', {'draft_spec': http_spec})
    assert isinstance(reply, AgentEvent)
    assert reply.kind == 'question'
    assert 'unchanged' in reply.text
    assert http_spec.model_dump() == before

    decision.updates = [ConversationUpdate(field='endpoints.0.input_fields', value_json='[{"name":"product_id","type":"string","required":true}]')]
    retry = session._interpret_reply({'kind': kind}, 'The complete input fields are product_id', {'draft_spec': http_spec})
    assert retry['field_updates']['endpoints.0.input_fields'][0]['name'] == 'product_id'


def test_invalid_rule_enum_gets_one_schema_guided_retry(http_spec):
    bad = ConversationDecision(intent='correct', updates=[ConversationUpdate(
        field='endpoints.0.business_rules',
        value_json='[{"name":"items","expression":"quantity must be an integer from 1 to 1000","operations":["type_check","range_check"]}]',
    )])
    good = bad.model_copy(deep=True)
    good.updates[0].value_json = good.updates[0].value_json.replace('"type_check","range_check"', '"other"')
    model = Mock()
    model.invoke.side_effect = [bad, good]
    interpreter = ClarificationInterpreter(Mock())
    before = http_spec.model_dump()
    result = interpreter._invoke_validated(model, [], http_spec)
    assert model.invoke.call_count == 2
    feedback = model.invoke.call_args.args[0][-1].content
    assert 'type_check' in feedback and 'Validation:' in feedback
    updated = apply_field_updates(http_spec, {u.field: __import__('json').loads(u.value_json) for u in result.updates})
    assert updated.endpoints[0].business_rules[0].operations == ['other']
    assert updated.endpoints[0].business_rules[0].expression == 'quantity must be an integer from 1 to 1000'
    assert http_spec.model_dump() == before


def test_schema_retry_is_bounded_and_never_becomes_approval(http_spec):
    bad = ConversationDecision(intent='correct', updates=[ConversationUpdate(
        field='endpoints.0.business_rules', value_json='[{"name":"x","expression":"x","operations":["int64"]}]',
    )])
    interpreter = ClarificationInterpreter(Mock())
    for second in [bad, ConversationDecision(intent='answer', answer_json='true')]:
        model = Mock()
        model.invoke.side_effect = [bad, second]
        result = interpreter._invoke_validated(model, [], http_spec)
        assert result.intent == 'correct'
        assert model.invoke.call_count == 2
        assert AgentSession._invalid_updates(http_spec, {u.field: __import__('json').loads(u.value_json) for u in result.updates}) is not None
