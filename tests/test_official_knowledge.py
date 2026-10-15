import json
from pathlib import Path
import pytest
from nl2service.evaluation.mysql_ecosystem import public_spec,generation_request
from nl2service.knowledge.official import OfficialKnowledgeSelector
from nl2service.render.official_mysql import OfficialMySQLRenderer,PROTO


def task():
    return json.loads(Path('nl2service/evaluation/mysql-composition-tasks.jsonl').read_text().splitlines()[0])


def test_private_oracles_are_not_serialized_into_generation():
    item = task()
    request = generation_request(item)
    assert item['private_setup_sql'] not in request
    assert "O'Brien" not in request
    assert 'private_cases' not in public_spec(item).model_dump_json()


def test_full_context_and_no_rag_share_same_pinned_corpus():
    spec=public_spec(task())
    full=OfficialKnowledgeSelector('official-full-context')
    bundle=full.select(spec)
    assert len(bundle.files)==3
    assert full.trace['reference_characters']<=28000
    assert all('SOURCE https://github.com/' in source and 'LICENSE' in source for source in bundle.files.values())
    none=OfficialKnowledgeSelector('official-none')
    assert none.select(spec).files=={}
    assert none.trace['manifest_sha256']==full.trace['manifest_sha256']


def test_wire_skeleton_is_not_a_mysql_business_template(tmp_path):
    spec=public_spec(task())
    files=OfficialMySQLRenderer().render_tree(spec)
    assert 'INSERT INTO' not in files['service.go']
    assert 'RegisterGreeterService' in files['main.go']
    assert 'trpc.group/trpc-go/trpc-database/mysql v1.0.0' in files['go.mod']
    assert '${NL2SERVICE_RPC_PORT}' in files['trpc_go.yaml']
    custom=tmp_path/'custom.proto';custom.write_text('syntax="proto3";')
    spec.service.proto_file=str(custom)
    with pytest.raises(ValueError,match='pinned'):
        OfficialMySQLRenderer().render_tree(spec)


def test_transaction_capability_keeps_callback_and_usage_dependencies():
    class Embeddings:
        calls=0
        input_tokens=0
        def embed(self,texts):
            self.calls+=1
            return [[1.0,0.0] for _ in texts]
    item=json.loads(Path('nl2service/evaluation/mysql-composition-tasks.jsonl').read_text().splitlines()[1])
    selector=OfficialKnowledgeSelector('official-rag',embeddings=Embeddings())
    bundle=selector.select(public_spec(item),'Greeter RPC configuration')
    assert set(bundle.examples)=={'mysql-client-and-config','mysql-transaction-and-rollback'}
    content='\n'.join(bundle.files.values())
    assert 'TxFunc func(*sql.Tx) error' in content
    assert 'fn := func(tx *sql.Tx) (err error)' in content
    assert 'otherwise they are not transactions' in content
    assert selector.trace['dependency_closed'] is True
    assert 'DERIVED API INTERPRETATION' in content
    assert 'losing original identity/type' in content


def test_pinned_dataset_and_snippets_survive_git_line_endings():
    import hashlib
    dataset=Path('nl2service/evaluation/mysql-composition-tasks.jsonl')
    lock=json.loads(dataset.with_name('mysql-composition-manifest.json').read_text())
    assert b'\r\n' not in dataset.read_bytes()
    assert hashlib.sha256(dataset.read_bytes()).hexdigest()==lock['dataset_sha256']
    root=Path('nl2service/knowledge')
    manifest=json.loads((root/'manifest.json').read_text())
    for bundle in manifest['bundles']:
        for entry in bundle['entries']:
            content=(root/entry['local_path']).read_bytes()
            assert b'\r\n' not in content
            assert hashlib.sha256(content).hexdigest()==entry['sha256']


def test_rpc_failure_still_checks_transaction_state():
    from nl2service.evaluation.mysql_ecosystem import evaluate_cases
    class Service:
        def call(self,payload):
            raise RuntimeError('RPC failure credential')
    class Database:
        password='credential'
        observed=[]
        def sql(self,statement):
            self.observed.append(statement)
            return 'unchanged'
    database=Database()
    result=evaluate_cases(Service(),database,[{'payload':{},'expected':{'error':'db_error'},'sql':'SELECT state','sql_expected':'unchanged'}])[0]
    assert database.observed==['SELECT state']
    assert result['checks']=={'rpc_response':False,'independent_database_state':True}
    assert result['passed'] is False
    assert 'credential' not in result['errors']['rpc']


def test_struct_read_mapping_contract_is_derived_from_public_schema():
    item=json.loads(Path('nl2service/evaluation/mysql-holdout-v1.jsonl').read_text(encoding='utf-8').splitlines()[2])
    renderer=OfficialMySQLRenderer();renderer.render_tree(public_spec(item))
    mapping=renderer.generation_contract['database_mapping']
    assert mapping['column_tag']=='db' and mapping['wire_tag']=='json'
    assert mapping['columns_by_table']['roster_members']==['team_id','member_id','role']
    refs=OfficialKnowledgeSelector('official-full-context').select(public_spec(item))
    assert 'var NameMapper = strings.ToLower' in '\n'.join(refs.files.values())
    assert 'does not read json tags' in '\n'.join(refs.files.values())
