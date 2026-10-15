import json
from pathlib import Path
from nl2service.evaluation.backends import public_spec,generation_request
from nl2service.knowledge.official import OfficialKnowledgeSelector
from nl2service.render.official_backends import OfficialBackendRenderer


class Embeddings:
    calls=0;input_tokens=0;hits=0;model='fixture'
    def embed(self,texts):self.calls+=1;return [[1.,0.] for _ in texts]


def tasks():return [json.loads(line) for line in Path('nl2service/evaluation/redis-kafka-dev-v1.jsonl').read_text(encoding="utf-8").splitlines()]


def test_backend_retrieval_closes_types_and_excludes_inactive_sources():
    for task in tasks():
        spec=public_spec(task);selector=OfficialKnowledgeSelector('official-rag',embeddings=Embeddings())
        refs=selector.select(spec,generation_request(task))
        assert len(refs.examples)==2
        assert all(name.startswith(task['backend']+'-') for name in refs.examples)
        assert not any(name.startswith('mysql-') for name in refs.examples)
        none=OfficialKnowledgeSelector('official-none');assert none.select(spec).files=={}
        full=OfficialKnowledgeSelector('official-full-context');assert len(full.select(spec).files)==3


def test_business_placeholder_has_no_backend_answer_and_private_cases_are_excluded():
    for task in tasks():
        files=OfficialBackendRenderer(task['backend']).render_tree(public_spec(task))
        assert 'Agent must implement' in files['service.go']
        assert 'private_cases' not in public_spec(task).model_dump_json()
        assert "e-alpha" not in generation_request(task) and "雪'O" not in generation_request(task)
        if task['backend']=='redis':assert 'goredis.New' in files['main.go'] and 'redis.UniversalClient' in files['main.go']
        else:assert 'RegisterKafkaHandlerService' in files['main.go'] and 'MaxRetry=-1' in files['main.go']


def test_explicit_plaintext_kafka_does_not_request_a_tls_certificate():
    from nl2service.spec.validator import ServiceSpecValidator
    import pytest
    from nl2service.render.renderer import ProtoContractError
    spec=public_spec(tasks()[1]);spec.kafka.tls=False
    assert not any(issue.field=='kafka.ca_file' for issue in ServiceSpecValidator().validate(spec).issues)
    spec.kafka.tls=True
    with pytest.raises(ProtoContractError,match='plaintext'):
        OfficialBackendRenderer('kafka').render_tree(spec)
