#!/usr/bin/env python3
"""Real API/CLI checks in an isolated session/history directory."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import uuid
import harness as h
from verify_quiet import quiet, turn_events, without_check_lines
ROOT=Path(__file__).resolve().parent

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine',choices=['openai','anthropic'],default='openai')
    args=parser.parse_args()
    try: h.load_prefix(); h.load_key(args.engine)
    except h.HarnessError as exc: print(str(exc),file=sys.stderr); return 2
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    folder=ROOT/'state'/('live-'+args.engine+'-'+stamp+'-'+uuid.uuid4().hex[:6])
    folder.mkdir(parents=True,mode=0o700)
    runtime=quiet(folder/'runtime')  # the verifier's answers are not read aloud
    env=os.environ.copy(); env['HARNESS_STATE_DIR']=str(runtime)
    audit='audit device permissions and credentials for local terminal, uh term units; give me read only commands for my user ID, permission mask, and whether OPENAI_API_KEY is set, without printing its value'
    marker='emerald-'+uuid.uuid4().hex[:8]
    cases=[
      ('noisy-audit-1',audit,'action_request',True,[],False),
      ('noisy-audit-2-cache-check',audit,'action_request',True,[],True),
      ('observation','I think the API key might be missing. This is just an observation; do not check or change anything.','observation',False,[],False),
      ('ambiguous-target','Delete that file we were talking about.','observation',False,[],False),
      ('explain-stt','What does show mod six four zero mean for a regular Linux file? Just explain; do not run anything.','observation',False,[],True),
      ('session-seed',f'The session marker is {marker}. State the marker back.','observation',False,['--session','memory-check'],False),
      ('session-recall','What is the session marker?','observation',False,['--session','memory-check'],False),
      ('continue-recall','State the session marker again.','observation',False,['--continue'],False),
    ]
    results=[]
    for name,query,intent,payload,options,use_stdin in cases:
        print('Checking '+args.engine+' '+name+'.',flush=True)
        log=folder/(name+'.usage.jsonl')
        command=[sys.executable,str(ROOT/'harness.py'),'--engine',args.engine,'--usage-log',str(log),*options]
        if not use_stdin: command.append(query)
        try: run=subprocess.run(command,input=query if use_stdin else None,text=True,capture_output=True,timeout=220,env=env)
        except subprocess.TimeoutExpired:
            results.append({'case':name,'passed':False,'error':'Test process timed out.'}); break
        events=turn_events([json.loads(line) for line in log.read_text().splitlines()] if log.exists() else [])  # model turns only
        last=events[-1] if events else {}
        passed=(run.returncode==0 and bool(run.stdout.strip()) and not without_check_lines(run.stderr) and last.get('status')=='accepted' and last.get('intent')==intent and last.get('has_execution_payload')==payload)
        if name=='ambiguous-target': passed=passed and '?' in run.stdout
        if name in {'session-seed','session-recall','continue-recall'}: passed=passed and marker in run.stdout
        results.append({'case':name,'passed':passed,'exit_code':run.returncode,'stdout':run.stdout,'stderr':run.stderr,'attempts':len(events),'usage':last.get('usage'),'intent':last.get('intent'),'has_execution_payload':last.get('has_execution_payload'),'response_id':last.get('response_id')})
        if last.get('status') in {'authentication_error','permission_error','quota_or_rate_limit','api_error'}: break
    recall=subprocess.run([sys.executable,str(ROOT/'harness.py'),'--recall',marker],text=True,capture_output=True,timeout=30,env=env)
    recall_ok=recall.returncode==0 and marker in recall.stdout
    db=sqlite3.connect(runtime/'history.db')
    try:
        rows=db.execute('SELECT engine,raw_input,normalized_input,status FROM history ORDER BY id').fetchall()
        database_ok=len(rows)==len(results) and all(r[0]==args.engine for r in rows)
        stt_ok=bool(rows) and 'term units' in rows[0][1] and 'Termux' in rows[0][2]
    finally: db.close()
    cache=[]
    for result in results[:2]:
        usage=result.get('usage') or {}
        cache.append(usage.get('cache_read_input_tokens',0)+(usage.get('input_tokens_details') or {}).get('cached_tokens',0))
    passed=len(results)==8 and all(r['passed'] for r in results) and recall_ok and database_ok and stt_ok
    report={'time_utc':stamp,'engine':args.engine,'prefix_sha256':h.PREFIX_SHA256,'cases':results,'all_passed':passed,'recall_passed':recall_ok,'sqlite_logging_passed':database_ok,'normalization_passed':stt_ok,'cache_tokens_first_two_calls':cache,'cache_hit_observed':len(cache)==2 and cache[1]>0,'note':'Real API calls; native execution and live microphone checks are recorded separately.'}
    path=folder/'report.json';path.write_text(json.dumps(report,indent=2)+'\n');path.chmod(0o600)
    (ROOT/'state'/('latest-live-'+args.engine+'-report.txt')).write_text(str(path)+'\n')
    verification_path=ROOT/'verification.json'
    verification=json.loads(verification_path.read_text()) if verification_path.exists() else {}
    verification.setdefault('production_live',{})[args.engine]={'status':'passed' if passed else 'failed','report':str(path),'cases_run':len(results),'cases_passed':sum(bool(r['passed']) for r in results),'recall':recall_ok,'sqlite':database_ok,'normalization':stt_ok,'cache_hit_observed':report['cache_hit_observed'],'cache_tokens':cache}
    verification_path.write_text(json.dumps(verification,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ['all_passed','recall_passed','sqlite_logging_passed','normalization_passed','cache_hit_observed','cache_tokens_first_two_calls']}))
    print('Report: '+str(path))
    return 0 if passed else 1

if __name__=='__main__': raise SystemExit(main())
