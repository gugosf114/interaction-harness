#!/data/data/com.termux/files/usr/bin/python
"""Real provider senses checks; reports contain metadata and text, never attachment bytes."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import time
import uuid

from lookup_gate import urls,displayed_sources
from senses_fixtures import create

ROOT=Path(__file__).resolve().parent
CASE_NAMES=['today','stable','fetch','image','pdf','image-followup','cache']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine',choices=['openai','anthropic'],required=True)
    parser.add_argument('--key-dir',type=Path,default=ROOT/'state')
    parser.add_argument('--resume',type=Path)
    parser.add_argument('--case',choices=CASE_NAMES,action='append')
    args=parser.parse_args()
    probe_env=os.environ.copy();probe_env.pop('LD_LIBRARY_PATH',None)
    probe=subprocess.run([str(ROOT/'harness'),'--help'],env=probe_env,text=True,capture_output=True,timeout=40)
    if probe.returncode or any(flag not in probe.stdout for flag in ('--no-web','--image','--file')):
        raise SystemExit('The launcher did not reach this senses build; no live requests were made.')
    folder=(args.resume or ROOT/'state'/'senses-checks'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+args.engine+'-'+uuid.uuid4().hex[:6])).resolve()
    folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    fixtures_path=folder/'fixtures.json'
    if fixtures_path.exists():fixtures=json.loads(fixtures_path.read_text())
    else:
        fixtures=create(folder);fixtures_path.write_text(json.dumps(fixtures,indent=2)+'\n')
    if args.case and 'image' in args.case or not fixtures.get('vision_session'):
        fixtures['vision_session']='vision-'+uuid.uuid4().hex[:8]
        fixtures_path.write_text(json.dumps(fixtures,indent=2)+'\n')
    report_path=folder/'report.json'
    report=json.loads(report_path.read_text()) if report_path.exists() else {'engine':args.engine,'cases':{},'attempts':[]}
    runtime=folder/'runtime';env=os.environ.copy();env.pop('LD_LIBRARY_PATH',None);env['HARNESS_STATE_DIR']=str(runtime)
    key_name='OPENAI_API_KEY' if args.engine=='openai' else 'ANTHROPIC_API_KEY'
    if not env.get(key_name):
        key_path=args.key_dir/('api-key' if args.engine=='openai' else 'anthropic-api-key')
        if key_path.exists():env[key_name]=key_path.read_text().strip()
    today=datetime.now(timezone.utc).date().isoformat()
    cases={
      'today':(f'Search the web now for the latest stable Python release as of today, {today}. Use the official Python downloads site and give the version and release date.',[]),
      'stable':('What does chmod 640 mean?',['--session','cache-check']),
      'fetch':('Fetch https://example.com and give me its title.',[]),
      'image':('What six-digit number is shown? Answer with the digits only.',['--session',fixtures['vision_session'],'--image',fixtures['image']]),
      'pdf':('Read the attached PDF and repeat its one sentence exactly.',['--file',fixtures['file']]),
      'image-followup':('What six-digit number was in the image I attached earlier? Answer with the digits only.',['--session',fixtures['vision_session']]),
      'cache':('What does chmod 640 mean?',['--session','cache-check']),
    }
    for name in (args.case or CASE_NAMES):
        query,options=cases[name]
        log=folder/(name+'-'+uuid.uuid4().hex[:6]+'.usage.jsonl')
        command=[str(ROOT/'harness'),'--engine',args.engine,'--timeout','120','--usage-log',str(log),*options,query]
        print('Checking '+args.engine+' '+name+'.',flush=True)
        started=time.monotonic()
        try:run=subprocess.run(command,env=env,text=True,capture_output=True,timeout=400)
        except subprocess.TimeoutExpired as exc:
            run=type('Run',(),{'returncode':124,'stdout':(exc.stdout or b'').decode() if isinstance(exc.stdout,bytes) else exc.stdout or '',
                              'stderr':'Verification timed out.'})()
        elapsed=round((time.monotonic()-started)*1000)
        events=[json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        row={};reply={};sources=[];counts={}
        if (runtime/'history.db').exists():
            db=sqlite3.connect(runtime/'history.db');db.row_factory=sqlite3.Row
            try:
                fetched=db.execute('SELECT * FROM history ORDER BY id DESC LIMIT 1').fetchone()
                if fetched:row=dict(fetched)
            finally:db.close()
        sources=json.loads(row.get('sources_json') or '[]');counts=json.loads(row.get('lookup_counts_json') or '{}')
        if row.get('status')=='accepted':
            session=json.loads((runtime/'sessions'/(row['session_id']+'.json')).read_text())
            reply=session['turns'][-1]['reply']
            sources=json.loads(row.get('sources_json') or '[]');counts=json.loads(row.get('lookup_counts_json') or '{}')
        cache=sum((e.get('usage') or {}).get('cache_read_input_tokens',0)+((e.get('usage') or {}).get('input_tokens_details') or {}).get('cached_tokens',0) for e in events)
        checks={'exit_zero':run.returncode==0,'sqlite_accepted':row.get('status')=='accepted',
                'correct_request_record':row.get('raw_input')==query,
                'four_fields':set(reply)=={'intent','cleaned_input','direct_answer','execution_payload'}}
        answer=reply.get('direct_answer','')
        if name=='today':
            shown=displayed_sources(sources,answer)
            checks.update(lookup=counts.get('total',0)>0,sources_printed='\nSources:\n' in run.stdout,
                          answer_urls_recorded=urls(answer)<={s['url'] for s in shown})
        elif name=='stable':checks.update(no_lookup=counts.get('total')==0,no_sources='Sources:' not in run.stdout)
        elif name=='fetch':checks.update(fetch_recorded=counts.get('fetch',0)>0,title_correct='Example Domain' in answer)
        elif name in ('image','image-followup'):checks['number_correct']=fixtures['number'] in answer
        elif name=='pdf':checks['sentence_correct']=fixtures['sentence'] in answer
        elif name=='cache':
            checks['cache_read_positive']=cache>0
            first_events=report['cases'].get('stable',{}).get('events',[])
            checks['same_tool_definitions']=bool(first_events and events) and first_events[-1].get('web_tools_sha256')==events[-1].get('web_tools_sha256')
        result={'case':name,'exit_code':run.returncode,'elapsed_ms':elapsed,'checks':checks,'passed':all(checks.values()),
                'stdout':run.stdout,'stderr':run.stderr,'reply':reply,'sources':sources,'lookup_counts':counts,
                'cache_read_tokens':cache,'events':events,'sqlite_row_id':row.get('id')}
        report['cases'][name]=result;report['attempts'].append(result)
        report.update(all_passed=all(report['cases'].get(n,{}).get('passed',False) for n in CASE_NAMES),
                      sqlite_database=str(runtime/'history.db'),money_reported=None,
                      money_note='The checked provider responses report tokens and tool use, not monetary charges; raw usage is preserved.')
        report_path.write_text(json.dumps(report,indent=2)+'\n');report_path.chmod(0o600)
        print(json.dumps({'case':name,'exit_code':run.returncode,'passed':result['passed'],'cache_read_tokens':cache,'lookups':counts.get('total'),'error':run.stderr[:180]}),flush=True)
    (ROOT/'state'/('latest-senses-'+args.engine+'.txt')).write_text(str(report_path)+'\n')
    print('Report: '+str(report_path),flush=True)
    return 0 if report['all_passed'] else 1


if __name__=='__main__':raise SystemExit(main())
