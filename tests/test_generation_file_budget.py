from nl2service.agent.main_agent import MainLLMAgent,RefinedRender
from nl2service.agent.session import MainAgentSessionState
from nl2service.agent.main_agent import RefinedImplementation
from nl2service.render.official_mysql import OfficialMySQLRenderer


def test_checksum_files_are_not_model_context_or_model_authored(monkeypatch):
    session=MainAgentSessionState(user_request='Implement behavior',rendered_files={
        'service.go':'package main\n','go.sum':'REAL DEPENDENCY CHECKSUM\n'})
    messages=MainLLMAgent._build_refine_messages(session)
    assert 'REAL DEPENDENCY CHECKSUM' not in messages[1].content
    monkeypatch.setattr(MainLLMAgent,'_invoke_structured',lambda *a,**k:('test',RefinedRender(files={
        'service.go':'package main\nfunc main() {}\n','go.sum':'MODEL INVENTED CHECKSUM'})))
    files=MainLLMAgent().refine_code(session).files
    assert files['go.sum']==session.rendered_files['go.sum']
    assert 'func main' in files['service.go']


def test_bound_module_uses_typed_output_and_preserves_platform_files(monkeypatch):
    session=MainAgentSessionState(user_request='Implement behavior',generation_contract=OfficialMySQLRenderer.generation_contract,
        rendered_files={'service.go':'placeholder','main.go':'platform wiring','go.mod':'pinned module','go.sum':'real checksums'})
    def invoke(self,**kwargs):
        assert kwargs['schema'] is RefinedImplementation
        return 'test',RefinedImplementation(implementation='package main\n',supporting_files={'main.go':'bad wiring','helper.go':'package main\n','go.mod':'bad module'})
    monkeypatch.setattr(MainLLMAgent,'_invoke_structured',invoke)
    files=MainLLMAgent().refine_code(session).files
    assert files['service.go']=='package main\n'
    assert files['main.go']=='platform wiring' and files['go.mod']=='pinned module'
    assert files['go.sum']=='real checksums' and 'helper.go' in files
