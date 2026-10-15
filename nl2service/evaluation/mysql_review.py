"""Paired public-contract review ablation on retained compiler-only outputs."""
from __future__ import annotations
import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from langgraph.graph import StateGraph, START, END
from nl2service.evaluation.mysql_ecosystem import BudgetProvider,public_spec,generation_request,evaluate_cases,summary
from nl2service.evaluation.mysql_runtime import MySQLRuntime,RPCService
from nl2service.evaluation.paired import digest
from nl2service.evaluation.runner import UsageTracker,EvaluationVerifier,BlockedDelivery
from nl2service.knowledge.official import OfficialKnowledgeSelector,ROOT
from nl2service.render.official_mysql import OfficialMySQLRenderer
from nl2service.runtime.checkpointer import SQLiteCheckpointRuntime
from nl2service.workflow.core import WorkflowCore
from nl2service.workflow.state import WorkflowState,structured_state_defaults


def review_graph(core,checkpointer):
    graph=StateGraph(WorkflowState)
    graph.add_node('contract_review',core._public_contract_review_node)
    graph.add_node('repair',core._repair_build_errors_node)
    graph.add_node('verify',core._verify_build_node)
    graph.add_edge(START,'contract_review')
    graph.add_conditional_edges('contract_review',lambda s:'repair' if s.get('status')=='contract_review_requested' else END)
    graph.add_conditional_edges('repair',lambda s:END if s.get('status')=='error' else 'verify')
    graph.add_conditional_edges('verify',lambda s:{'build_verification_failed':'repair','deterministic_repair_applied':'verify'}.get(s.get('status'),END))
    return graph.compile(checkpointer=checkpointer)


def main():
    parser=argparse.ArgumentParser()
    for name in ('source-report','source-artifacts','report','artifacts'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    original=json.loads(args.source_report.read_text(encoding='utf-8'))
    manifest_hash=hashlib.sha256((ROOT/'manifest.json').read_bytes()).hexdigest()
    if not original['complete'] or manifest_hash!=original['metadata']['knowledge_manifest_sha256']:
        raise ValueError('Require a complete compiler-only report and its unchanged official corpus.')
    tasks={task['id']:task for task in (json.loads(line) for line in Path(__file__).with_name('mysql-composition-tasks.jsonl').read_text().splitlines())}
    results=[]
    metadata={'source_report_sha256':hashlib.sha256(args.source_report.read_bytes()).hexdigest(),
              'source_revision':original['metadata']['revision'],
              'revision':subprocess.run(['git','rev-parse','HEAD'],capture_output=True,text=True,check=True).stdout.strip(),
              'model':original['metadata']['model'],'knowledge_manifest_sha256':manifest_hash,
              'max_initial_compiler_repairs':3,'max_post_review_repairs':3,'max_total_repairs':6,
              'max_contract_reviews':1,'max_output_tokens':8192,
              'scope':'Development paired workflow ablation. Same retained compiler-only code; reviewer gets only public request/IR/code/references. Private tests only after repair; no scoring feedback.'}
    def save(complete):
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps({'complete':complete,'metadata':metadata,'results':results,'metrics':summary(results)},indent=2),encoding='utf-8')
    save(False)
    with MySQLRuntime() as database:
        for row in original['results']:
            result={**row,'model_calls':row['model_calls'],'review_build_attempts':[],'compiler_only_passed':row['passed'],
                    'compiler_only_assertions':row['assertions'],'private_scoring_feedback_to_reviewer':False}
            print('Reviewing',row['id'],row['mode'],flush=True)
            task=tasks[row['id']];spec=public_spec(task);request=generation_request(task)
            if digest(spec.model_dump(mode='json'))!=row['public_ir_sha256'] or digest(request)!=row['public_request_sha256']:
                raise ValueError('Public generation prefix changed.')
            source=args.source_artifacts/row['mode']/row['id'];root=args.artifacts/row['mode']/row['id'];root.mkdir(parents=True,exist_ok=True)
            files={p.relative_to(source).as_posix():p.read_text(encoding='utf-8') for p in source.rglob('*')
                   if p.is_file() and (p.suffix=='.go' or p.name in ('go.mod','go.sum','trpc_go.yaml'))}
            result['review_initial_code_sha256']=digest(files)
            tracker=UsageTracker();core=WorkflowCore(provider=BudgetProvider(tracker),model=metadata['model'],github_provider=BlockedDelivery())
            core.contract_review_enabled=True;core.renderer=OfficialMySQLRenderer();core.example_selector=OfficialKnowledgeSelector(row['mode'])
            bundle=core.example_selector.select(spec,request)
            if bundle.examples!=row['retrieval']['selected_bundles']:
                raise ValueError('Review reference selection differs from original generation.')
            verifier=EvaluationVerifier();core.verifier=verifier;core.renderer.write_tree(files,root)
            initial={**structured_state_defaults(),'draft_spec':spec,'user_request':request,'model':metadata['model'],
                     'rendered_files':files,'output_dir':str(root),'status':row['status'],'example_reference_files':bundle.files,
                     'build_feedback':row['build_attempts'][-1]['feedback'] if row['status']!='verified' and row['build_attempts'] else None,
                     'contract_review_required':True,'contract_review_complete':False,
                     'code_repair_calls':0,'repair_history':row['repair_history']}
            trace=[];error=None
            with SQLiteCheckpointRuntime(root/'checkpoint.db') as runtime:
                graph=review_graph(core,runtime.checkpointer);config={'configurable':{'thread_id':row['id']},'recursion_limit':20}
                try:
                    for update in graph.stream(initial,config,stream_mode='updates'):
                        trace.extend({'node':node,'status':state.get('status')} for node,state in update.items())
                except Exception as exc:
                    error=f'{type(exc).__name__}: {exc}'
                final=graph.get_state(config).values
            assertions=[]
            if final.get('status')=='verified' and not error:
                tables=[t['name'] for t in task['tables']]
                database.sql('SET FOREIGN_KEY_CHECKS=0;'+''.join(f'DROP TABLE IF EXISTS `{name}`;' for name in tables)+'SET FOREIGN_KEY_CHECKS=1;')
                database.sql(task['private_setup_sql'])
                try:
                    with RPCService(root,database) as service:
                        assertions=evaluate_cases(service,database,task['private_cases'])
                except Exception as exc:
                    error=str(exc).replace(database.password,'[redacted]')
            result.update(passed=len(assertions)==len(task['private_cases']) and all(a['passed'] for a in assertions) and not error,
                          status=final.get('status'),error=error or final.get('error'),assertions=assertions,
                          model_calls=row['model_calls']+tracker.calls,additional_model_calls=tracker.calls,review_build_attempts=verifier.builds,
                          contract_review=final.get('contract_review',{}),review_trace=trace,
                          review_retrieval_trace=core.example_selector.trace,
                          post_review_repair_calls=final.get('code_repair_calls'),
                          initial_compiler_repair_calls=max(0,len(row['model_calls'])-1),repair_history=final.get('repair_history',[]),
                          review_final_code_sha256=digest(final.get('rendered_files',{})))
            results.append(result);save(False)
            print('  before=',row['passed'],'after=',result['passed'],flush=True)
    save(True)


if __name__=='__main__':
    main()
