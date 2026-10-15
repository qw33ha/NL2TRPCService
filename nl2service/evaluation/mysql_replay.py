"""Replay retained generated projects, without generation or scoring feedback."""
from __future__ import annotations
import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from nl2service.evaluation.mysql_ecosystem import evaluate_cases, summary
from nl2service.evaluation.mysql_runtime import MySQLRuntime, RPCService
from nl2service.build.verify import GoBuildVerifier


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source-report',type=Path,required=True)
    parser.add_argument('--artifacts',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--audit-all-artifacts',action='store_true')
    args=parser.parse_args()
    original=json.loads(args.source_report.read_text(encoding='utf-8'))
    if not original['complete']:
        raise ValueError('Replay requires a complete retained generation report.')
    tasks={task['id']:task for task in (json.loads(line) for line in Path(__file__).with_name('mysql-composition-tasks.jsonl').read_text().splitlines())}
    results=[]
    metadata={'source_report_sha256':hashlib.sha256(args.source_report.read_bytes()).hexdigest(),
              'generation_revision':original['metadata']['revision'],
              'observation_revision':subprocess.run(['git','rev-parse','HEAD'],capture_output=True,text=True,check=True).stdout.strip(),
              'model_calls':0,'audit_all_artifacts':args.audit_all_artifacts,
              'scope':'Observation replay of retained code. No Agent generation, repair, or final scoring feedback. Artifact behavior is separate from original workflow approval.'}
    def save(complete):
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps({'complete':complete,'metadata':metadata,'results':results,'metrics':summary(results)},indent=2),encoding='utf-8')
    save(False)
    with MySQLRuntime() as database:
        for row in original['results']:
            result={**row,'model_calls':[],'assertions':[],'error':row.get('error'),
                    'original_workflow_status':row['status'],'original_workflow_passed':row['passed'],
                    'original_workflow_error':row.get('error')}
            task=tasks[row['id']]
            root=args.artifacts/row['mode']/row['id']
            eligible=row['status']=='verified'
            if args.audit_all_artifacts:
                sources={p.relative_to(root).as_posix():p.read_text(encoding='utf-8')
                         for p in root.rglob('*') if p.is_file() and (p.suffix=='.go' or p.name in ('go.mod','go.sum','trpc_go.yaml'))}
                build=GoBuildVerifier().verify(sources)
                eligible=build.success
                result['audit_build']={'success':build.success,'feedback':build.feedback}
                result['status']='artifact_verified' if eligible else 'artifact_build_failed'
                result['error']=None if eligible else build.feedback
                result['passed']=False
            if eligible:
                files={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in root.rglob('*') if p.is_file() and (p.suffix=='.go' or p.name in ('go.mod','go.sum','trpc_go.yaml'))}
                result['retained_project_files']=files
                tables=[t['name'] for t in task['tables']]
                database.sql('SET FOREIGN_KEY_CHECKS=0;'+''.join(f'DROP TABLE IF EXISTS `{name}`;' for name in tables)+'SET FOREIGN_KEY_CHECKS=1;')
                database.sql(task['private_setup_sql'])
                try:
                    with RPCService(root,database) as service:
                        result['assertions']=evaluate_cases(service,database,task['private_cases'])
                except Exception as exc:
                    result['error']=str(exc).replace(database.password,'[redacted]')
                result['passed']=len(result['assertions'])==len(task['private_cases']) and all(case['passed'] for case in result['assertions']) and not result['error']
                print(row['id'],row['mode'],'passed',result['passed'],flush=True)
            results.append(result);save(False)
    save(True)


if __name__=='__main__':
    main()
