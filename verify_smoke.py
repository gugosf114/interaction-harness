#!/data/data/com.termux/files/usr/bin/python
"""Live one-off calls with four-field, display, cache and SQLite receipts.

The aliases carry --loop -y, which runs a returned command and asks for another model turn. These
checks are about one call that prints and runs nothing, so they call this folder's launcher with the
alias's engine, model and effort, and without --loop -y.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
import sqlite3
import time
import uuid
from verify_quiet import quiet, turn_events, without_check_lines

from verify_repl import terminal

ROOT=Path(__file__).resolve().parent
FIELDS={'intent','cleaned_input','direct_answer','execution_payload'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine',choices=['openai','anthropic'],required=True)
    args=parser.parse_args()
    alias='g1' if args.engine=='openai' else 'g2'
    model='gpt-6.1-sol' if args.engine=='openai' else 'claude-opus-5-5'
    launcher=shlex.quote(str(ROOT/'harness'))+' --engine '+args.engine+' --model '+model+' --effort max'
    label='OpenAI' if args.engine=='openai' else 'Claude'
    query=f"echo 'Testing {label} API connection'"
    folder=ROOT/'state'/'diagnostics'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+args.engine+'-'+uuid.uuid4().hex[:6])
    folder.mkdir(parents=True,mode=0o700)
    runtime=quiet(folder/'runtime')  # the verifier's answers are not read aloud
    env=os.environ.copy();env.pop('LD_LIBRARY_PATH',None);env['HARNESS_STATE_DIR']=str(runtime)
    cases=[];event_count=0
    for number in (1,2):
        command=launcher+' '+shlex.quote(query)
        started=time.monotonic()
        run=terminal(command,env,timeout=220)
        wall_ms=round((time.monotonic()-started)*1000)
        (folder/f'call-{number}-terminal.txt').write_text(run['transcript'])
        events_path=runtime/'usage.jsonl'
        all_events=turn_events([json.loads(line) for line in events_path.read_text().splitlines()] if events_path.exists() else [])  # model turns only
        events=all_events[event_count:];event_count=len(all_events)
        rows=[]
        if (runtime/'history.db').exists():
            db=sqlite3.connect(runtime/'history.db');db.row_factory=sqlite3.Row
            try:rows=[dict(r) for r in db.execute('SELECT * FROM history ORDER BY id')]
            finally:db.close()
        row=rows[-1] if rows else {}
        session_path=runtime/'sessions'/(str(row.get('session_id'))+'.json')
        reply={}
        if session_path.exists():reply=json.loads(session_path.read_text())['turns'][-1]['reply']
        expected=reply.get('direct_answer','')
        if reply.get('execution_payload'):expected+='\n\n'+reply['execution_payload'].strip()
        expected+='\n'
        inputs=outputs=cache=created=hits=latency=0
        metrics_present=bool(events)
        for event in events:
            usage=event.get('usage') or {}
            read=usage.get('cache_read_input_tokens',0)+(usage.get('input_tokens_details') or {}).get('cached_tokens',0)
            creation=usage.get('cache_creation_input_tokens',0)
            inputs+=usage.get('input_tokens',0)+usage.get('cache_read_input_tokens',0)+creation
            outputs+=usage.get('output_tokens',0);cache+=read;created+=creation;hits+=int(read>0)
            latency+=event.get('elapsed_ms',0)
            metrics_present=metrics_present and 'input_tokens' in usage and (
                'cache_read_input_tokens' in usage or 'cached_tokens' in (usage.get('input_tokens_details') or {}))
        checks={
            'exit_zero':run['exit_code']==0 and not run['timed_out'],
            'strict_four_fields':set(reply)==FIELDS and reply.get('intent') in {'observation','action_request'}
                and all(isinstance(reply.get(k),str) and reply[k].strip() for k in ('cleaned_input','direct_answer'))
                and (reply.get('execution_payload') is None or isinstance(reply.get('execution_payload'),str)),
            'observation_has_no_command':reply.get('intent')!='observation' or reply.get('execution_payload') is None,
            'display_gate':without_check_lines(run['transcript'])==expected,
            'provider_cache_metrics_reported':metrics_present,
            'sqlite_transaction':len(rows)==number and row.get('status')=='accepted'
                and row.get('engine')==args.engine and row.get('raw_input')==query,
            'sqlite_reply_matches':all(row.get(k)==reply.get(k) for k in FIELDS),
            'sqlite_metrics_match':all(row.get(k)==v for k,v in {
                'input_tokens':inputs,'output_tokens':outputs,'cache_read_tokens':cache,
                'cache_creation_tokens':created,'cache_hit_requests':hits,'latency_ms':latency,
                'tokens_used':inputs+outputs}.items()),
            'latency_recorded':bool(row.get('latency_ms')),
            'command_not_executed':row.get('execution_result') is None,
        }
        result={'call':number,'command':command,'exit_code':run['exit_code'],'wall_ms':wall_ms,
                'api_latency_ms':latency,'input_tokens':inputs,'output_tokens':outputs,
                'cache_read_tokens':cache,'cache_creation_tokens':created,'cache_hit_requests':hits,
                'api_attempts':len(events),'response_ids':[e.get('response_id') for e in events],
                'model_returned':[e.get('model_returned') for e in events],
                'sqlite_row_id':row.get('id'),'reply':reply,'checks':checks,'passed':all(checks.values())}
        cases.append(result)
        if not result['passed']:break
    report={'engine':args.engine,'alias':alias,'query':query,'sqlite_database':str(runtime/'history.db'),
            'cases':cases,'all_passed':len(cases)==2 and all(c['passed'] for c in cases),
            'cache_reuse_observed':any(c['cache_read_tokens']>0 for c in cases)}
    path=folder/'report.json';path.write_text(json.dumps(report,indent=2)+'\n');path.chmod(0o600)
    (ROOT/'state'/('latest-smoke-'+args.engine+'.txt')).write_text(str(path)+'\n')
    print(json.dumps({'report':str(path),'all_passed':report['all_passed'],'cache_reuse_observed':report['cache_reuse_observed'],
                     'calls':[{k:c[k] for k in ('call','exit_code','api_latency_ms','wall_ms','input_tokens','cache_read_tokens','cache_hit_requests')} for c in cases]}),flush=True)
    return 0 if report['all_passed'] else 1


if __name__=='__main__':raise SystemExit(main())
