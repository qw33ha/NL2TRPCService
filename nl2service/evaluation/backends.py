"""Actual LangGraph generation and Redis/Kafka RPC/broker/consumer validation."""
import argparse,hashlib,json,subprocess,time
from pathlib import Path
from nl2service.evaluation.mysql_ecosystem import BudgetProvider,summary
from nl2service.evaluation.runner import UsageTracker,EvaluationVerifier,BlockedDelivery
from nl2service.evaluation.paired import generation_graph,digest
from nl2service.evaluation.backend_runtime import BackendRuntime,BackendRPCService,REDIS_IMAGE,KAFKA_IMAGE
from nl2service.render.official_backends import OfficialBackendRenderer
from nl2service.render.official_mysql import PROTO
from nl2service.spec.models import ServiceSpec
from nl2service.workflow.core import WorkflowCore
from nl2service.workflow.state import structured_state_defaults
from nl2service.knowledge.official import OfficialKnowledgeSelector,ROOT
from nl2service.runtime.checkpointer import SQLiteCheckpointRuntime

MODES=('official-none','official-full-context','official-rag')


def public_spec(task):
    return ServiceSpec(service={'name':task['id'],'module':'example.com/'+task['id'],'mode':'rpc','proto_file':str(PROTO)},
                       redis=task.get('redis',{}),kafka=task.get('kafka',{}),deploy={'enabled':False},repo={'owner':'example','name':task['id']})


def generation_request(task):
    binding='s.cache is github.com/redis/go-redis/v9 UniversalClient created by official goredis plugin.' if task['backend']=='redis' else 's.producer is the official trpc-database/kafka Client. Consumer registration and observation are platform-managed.'
    return 'Implement the bound storageService.Execute method in service.go, plus any additional symbol in the authored module contract. Platform main/config/module/checksums are immutable. '+binding+' '+task['request']


def evaluate(task,root,backend):
    results=[]
    with BackendRPCService(root,backend) as service:
        if backend.kind=='kafka':service.consumer_ready()
        for i,case in enumerate(task['private_cases']):
            checks={};observations={};errors={}
            try:
                if case.get('restart'):
                    service.restart()
                    if backend.kind=='kafka':service.consumer_ready()
                if case.get('wait_seconds'):time.sleep(case['wait_seconds'])
                if case.get('backend_pause'):backend.pause()
                if 'payload' in case:
                    actual=service.call(case['payload']);observations['rpc']=actual;checks['rpc_response']=actual==case['expected']
                if case.get('backend_pause'):backend.unpause()
                if case.get('observe'):
                    actual=backend.redis(*case['observe']);observations['redis']=actual;checks['independent_redis_state']=actual==case['observe_expected']
                if case.get('ttl_key'):
                    actual=int(backend.redis('PTTL',case['ttl_key']));observations['ttl_ms']=actual;checks['expiration_configured']=0<actual<=case['ttl_max_ms']
                if case.get('consumer_expected'):checks['official_consumer_result']=service.wait_event(case['consumer_expected'])
                if case.get('broker_expected') or 'message_count' in case:
                    records=backend.messages();observations['broker_records']=records
                    if 'message_count' in case:checks['invalid_input_did_not_publish']=len(records)==case['message_count']
                    else:
                        key,payload=case['broker_expected'];checks['independent_message_content']=any(k==key and json.loads(v)==payload for k,v in records if v.startswith('{'))
                if case.get('inject'):
                    backend.inject(case['inject']);deadline=time.monotonic()+15
                    while time.monotonic()<deadline:
                        text=(root/'rpc-runtime.log').read_text(encoding='utf-8',errors='replace')
                        if 'EVENT_ERROR' in text:break
                        time.sleep(.1)
                    checks['invalid_consumer_event_rejected']='EVENT_ERROR' in text
            except Exception as exc:errors['runtime']=str(exc);checks['runtime']=False
            finally:backend.unpause()
            results.append({'index':i,'passed':bool(checks) and all(checks.values()),'checks':checks,'observations':observations,'errors':errors,'restart':case.get('restart',False)})
        if backend.kind=='kafka':
            records=backend.messages();results[-1]['observations']['after_failure_broker_records']=records
            results[-1]['observations']['failed_publish_may_have_arrived']=any(k=='e-fail' for k,v in records)
    return results


def run(task,mode,model,artifacts,backend):
    root=artifacts/mode/task['id'];root.mkdir(parents=True,exist_ok=True)
    tracker=UsageTracker();verifier=EvaluationVerifier();core=WorkflowCore(provider=BudgetProvider(tracker),model=model,github_provider=BlockedDelivery())
    core.contract_review_enabled=False;core.renderer=OfficialBackendRenderer(task['backend']);core.example_selector=OfficialKnowledgeSelector(mode);core.verifier=verifier
    spec=public_spec(task);request=generation_request(task)
    initial={**structured_state_defaults(),'draft_spec':spec,'user_request':request,'model':model,'output_dir':str(root),'gate_confirmed':True,'target_phase':'verified'}
    trace=[];error=None;scaffold=None
    with SQLiteCheckpointRuntime(root/'checkpoint.db') as runtime:
        graph=generation_graph(core,runtime.checkpointer);config={'configurable':{'thread_id':task['id']},'recursion_limit':40}
        try:
            for update in graph.stream(initial,config,stream_mode='updates'):
                for name,value in update.items():
                    trace.append({'node':name,'status':value.get('status')})
                    if name=='render':scaffold=digest(value['rendered_files'])
        except Exception as exc:error=type(exc).__name__+': '+str(exc)
        final=graph.get_state(config).values
    assertions=[]
    if final.get('status')=='verified' and not error:
        backend.reset()
        try:assertions=evaluate(task,root,backend)
        except Exception as exc:error=type(exc).__name__+': '+str(exc)
    return {'id':task['id'],'backend':task['backend'],'mode':mode,'status':final.get('status'),'error':error or final.get('error'),
            'passed':len(assertions)==len(task['private_cases']) and all(a['passed'] for a in assertions) and not error,
            'assertions':assertions,'planned_assertions':len(task['private_cases']),'model_calls':tracker.calls,'build_attempts':verifier.builds,
            'retrieval':final.get('retrieval_trace',{}),'repair_history':final.get('repair_history',[]),'trace':trace,
            'public_ir_sha256':digest(spec.model_dump(mode='json')),'public_request_sha256':digest(request),'scaffold_sha256':scaffold,
            'private_scoring_feedback_to_model':False}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--report',type=Path,required=True);parser.add_argument('--artifacts',type=Path,required=True)
    parser.add_argument('--modes',nargs='+',choices=MODES,default=list(MODES));parser.add_argument('--model',default='gpt-4.1-2025-04-14')
    args=parser.parse_args();dataset=Path(__file__).with_name('redis-kafka-dev-v1.jsonl');lock=json.loads(dataset.with_suffix('.manifest.json').read_text(encoding="utf-8"))
    assert hashlib.sha256(dataset.read_bytes()).hexdigest()==lock['dataset_sha256']
    tasks=[json.loads(line) for line in dataset.read_text(encoding="utf-8").splitlines()];rows=[]
    metadata={'revision':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'dataset_sha256':lock['dataset_sha256'],'dataset_status':lock['dataset_status'],'corpus_sha256':hashlib.sha256((ROOT/'manifest.json').read_bytes()).hexdigest(),'model':args.model,'output_tokens_per_call':8192,'max_repairs':3,'reference_character_cap':28000,'contract_review':False,'images':{'redis':REDIS_IMAGE,'kafka':KAFKA_IMAGE},'consumer_error_policy':'MaxRetry=-1: no retries; official plugin marks failed message progress. Output is observation only, not durable processing; no exactly-once/offset-commit guarantee.'}
    def save(complete):
        args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_bytes((json.dumps({'complete':complete,'planned_total':len(tasks)*len(args.modes),'metadata':metadata,'results':rows,'metrics':summary(rows)},indent=2)+'\n').encode())
    save(False)
    for index,task in enumerate(tasks):
        with BackendRuntime(task['backend']) as backend:
            modes=tuple(args.modes);order=modes[index%len(modes):]+modes[:index%len(modes)]
            for mode in order:
                print('Generating',task['id'],mode,flush=True);row=run(task,mode,args.model,args.artifacts,backend);rows.append(row);save(False)
                print('  passed=',row['passed'],'cases=',sum(a['passed'] for a in row['assertions']),'/',row['planned_assertions'],flush=True)
    save(True)


if __name__=='__main__':main()
