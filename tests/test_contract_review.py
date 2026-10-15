import json
import pytest
from nl2service.agent.contract_review import ContractReview,ContractFinding,review_contract
from nl2service.agent.session import MainAgentSessionState
from nl2service.workflow.core import WorkflowCore
from nl2service.workflow.conversation_graph import ConversationalServiceWorkflow
from nl2service.evaluation.mysql_ecosystem import public_spec
from pathlib import Path


def session():
    task=json.loads(Path('nl2service/evaluation/mysql-composition-tasks.jsonl').read_text().splitlines()[0])
    return MainAgentSessionState(user_request='Return JSON business errors.',draft_spec=public_spec(task),
        rendered_files={'service.go':'return payload, err'},reference_files={'official/api':'wraps error'})


class Provider:
    def __init__(self,result): self.result=result;self.packet=None
    def get_model(self,name): return self
    def with_structured_output(self,schema): return self
    def invoke(self,messages):
        self.packet=json.loads(messages[1].content)
        return self.result


def test_critic_receives_only_public_evidence_and_rejects_invented_quotes():
    provider=Provider(ContractReview(findings=[ContractFinding(file='service.go',code_quote='return payload, err',
        requirement_quote='JSON business errors',problem='Payload discarded',source_quote='wraps error')]))
    assert len(review_contract(session(),provider,'test').findings)==1
    assert set(provider.packet)=={'request','spec','files','references','compiler_diagnostics'}
    provider.result.findings[0].source_quote='an invented API guarantee'
    with pytest.raises(ValueError,match='framework source'):
        review_contract(session(),provider,'test')


def test_review_routes_before_delivery_and_cannot_reset_repair_budget():
    assert ConversationalServiceWorkflow._route_after_build({'status':'verified','contract_review_required':True})=='contract_review'
    assert ConversationalServiceWorkflow._route_after_build({'status':'verified','contract_review_required':True,'contract_review_complete':True})=='approve_github'
    core=WorkflowCore(provider=Provider(ContractReview()))
    packet=session()
    state={'draft_spec':packet.draft_spec,'user_request':packet.user_request,'rendered_files':packet.rendered_files,
           'contract_review_required':True,'code_repair_calls':3,'build_feedback':'Review findings'}
    result=core._repair_build_errors_node(state)
    assert result['status']=='error'
    assert 'budget exhausted' in result['error']
    assert core.provider.packet is None


def test_empty_critic_findings_cannot_approve_uncompilable_code():
    core=WorkflowCore(provider=Provider(ContractReview()))
    packet=session()
    state={'draft_spec':packet.draft_spec,'user_request':packet.user_request,'rendered_files':packet.rendered_files,
           'status':'error','build_feedback':'Go compiler failed'}
    result=core._public_contract_review_node(state)
    assert result['status']=='error'
    assert core.provider.packet['compiler_diagnostics']=='Go compiler failed'
