#!/data/data/com.termux/files/usr/bin/python
"""Live API-tool receipts through the actual Termux launcher; private isolated state."""
import argparse
import contextlib
import json
import os
from pathlib import Path
import secrets
import shlex
import sqlite3
import sys
import time

import launch
from native_tools import handle
from api_tools_config import TOOLS, DEFAULT_OPTIONS, write_json
from senses_fixtures import create

ROOT=Path(__file__).resolve().parent


def allowed(request, state, marker):
    if request.get('op')!='exec':return False
    command=request.get('command','')
    try:parts=shlex.split(command)
    except ValueError:return False
    prefix='Remote MCP request: android_notification_list '
    if parts[:2]==['printf','%s'] and len(parts)==3 and parts[2].startswith(prefix):
        try:return json.loads(parts[2][len(prefix):])=={'limit':5}
        except ValueError:return False
    if parts[:1]==['printf'] and len(parts)<=3:
        return all(x in ('printf','%s','%s\\n',marker,'4919','HARNESS-TOOLS-PROOF') for x in parts)
    if parts and parts[0].endswith('/agentbridge-call'):
        return len(parts)==3 and parts[1]=='android_notification_list' and json.loads(parts[2])=={'limit':5}
    if len(parts)==3 and parts[0].endswith('/python') and parts[1]==str(ROOT/'api_tools_native.py'):
        path=Path(parts[2]).resolve()
        if not path.is_relative_to(state):return False
        job=json.loads(path.read_text())
        if job['kind']=='memory':return Path(job['state']).resolve()==state
        if job['kind']=='computer':
            return job.get('target')=='hidden:astra-api-proof' and all((x.get('type') or x.get('name')) in ('screenshot','cursor_position','wait') for x in job['actions'])
        if job['kind']=='browser':return job['name'] in ('list_tabs','get_page_text','read_page','screenshot')
        if job['kind'] in ('text_editor','apply_patch'):
            target=Path(job['args'].get('path','')).resolve()
            return target.is_relative_to(state)
    return False


def prompts(case,marker,state):
    file=str(state/'edit-proof.txt')
    table={
        'web_search': ['Use web search to find the current Python stable release on python.org.'],
        'web_fetch': ['Fetch https://example.com and give its page title.'],
        'functions': [f'Use harness_command to run exactly printf {marker}. Report its output.'],
        'custom_tools': [f'Use local_command to run exactly printf {marker}. Report its output.'],
        'namespaces': [f'Use the local namespace command tool to run exactly printf {marker}. Report its output.'],
        'shell': [f'Use the shell/bash API tool to run exactly printf {marker}. Report its output.'],
        'hosted_shell': [f'Use the hosted shell to run printf {marker}. Report its output.'],
        'code_execution': ['Use the provider code execution tool to compute 137 * 149. Report the code result.'],
        'computer': ['Use the computer API tool to take a screenshot. Name the app shown. Capture only.'],
        'browser': ['Use the browser API tool to list the open tabs. Return their count. Do not navigate or click.'],
        'mcp_local': ['Use the local phone MCP tool to list the last five notifications on my phone. Call android_notification_list with limit 5. Report how many it returned.'],
        'mcp_remote': ['Use the remote phone MCP tool to list the last five notifications on my phone. Call android_notification_list with limit 5. Report how many it returned.'],
        'memory': [f'Use the memory tool to create /memories/tool-proof.md containing exactly {marker}.',
                   'Start with your saved memory folder. Read /memories/tool-proof.md and return its exact contents.'],
        'text_editor': [f'Use the text editor API tool to read {file}, replace apple with orange once, then read the file again. Report its new contents.'],
        'apply_patch': [f'Use apply_patch to update {file}: replace apple with orange. The file currently contains apple followed by a newline.'],
        'tool_search': [f'Use tool search to find the local command tool, then use it to run exactly printf {marker}. Report the result.'],
        'programmatic': [f'Use programmatic tool calling: write code that calls harness_command with command printf {marker}, then prints the returned stdout. Use the programmatic route, not a direct function call.'],
        'files': ['Read the attached PDF. Return the exact sentence in it.'],
        'file_search': ['Use file search to read the uploaded harness proof note. What marker does it contain?'],
        'skills': ['Use the uploaded harness proof skill. Read its SKILL.md and report its secret proof marker.'],
        'image_generation': ['Use the image generation tool to make a simple small blue circle on a white background. Report when the image is ready.'],
        'background': ['What is 137 * 149? Return the result.'],
        'advisor': ['Consult the advisor tool once to check whether 137 * 149 equals 20413. Give the checked result.'],
        'context_editing': [f'Use harness_command three times in order. Each command must be exactly printf {marker}. After all three results, state the output.'],
        'compaction': [f'Remember this test marker: {marker}. Reply with the marker.',
                       'What test marker did I give you earlier? Return it exactly.'],
        'history_cache': [f'Remember this marker: {marker}. '+('The kettle is blue and the shelf is oak. '*160),
                          'Keep the marker from my prior message. '+('The paper box holds seven wooden spoons. '*160),
                          'Return the original test marker exactly.'],
    }
    return table[case]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine',choices=['openai','anthropic'],required=True)
    parser.add_argument('--case',choices=list(TOOLS),required=True)
    parser.add_argument('--state',type=Path)
    parser.add_argument('--options-file',type=Path)
    parser.add_argument('--key-dir',type=Path,default=Path('/data/data/com.termux/files/home/interaction-harness/state'))
    args=parser.parse_args()
    state=(args.state or ROOT/'state/api-tools/live'/args.engine/args.case).resolve()
    state.mkdir(parents=True,exist_ok=True,mode=0o700)
    marker='tools-'+secrets.token_hex(6)
    variables={'openai':('OPENAI_API_KEY','api-key'),'anthropic':('ANTHROPIC_API_KEY','anthropic-api-key')}
    env,keyfile=variables[args.engine]
    if not os.environ.get(env):os.environ[env]=(args.key_dir/keyfile).read_text().strip()
    os.environ['HARNESS_STATE_DIR']=str(state)
    config={name:False for name in TOOLS};config[args.case]=True
    if args.case in ('web_search','web_fetch') and args.engine=='openai':config.update(web_search=True,web_fetch=True)
    config['history_cache']=args.engine=='anthropic'
    options={**DEFAULT_OPTIONS,'computer_target':'hidden:astra-api-proof'}
    if args.options_file:options.update(json.loads(args.options_file.read_text()))
    if args.case=='context_editing':config['functions']=True;options['compaction_threshold']=1000
    if args.case=='compaction':options['compaction_threshold']=1
    config['options']=options;write_json(state/'tools.json',config)
    fixtures=create(state/'fixtures');(state/'edit-proof.txt').write_text('apple\n')
    queries=prompts(args.case,marker,state);runs=[];commands=[]
    def checked(request):
        if not allowed(request,state,marker):result={'error':'The live proof blocked a command outside its test scope.'}
        else:result=handle(request)
        commands.append({'request':request,'result':result});write_json(state/'commands.json',commands);return result
    launch.handle=checked
    for number,query in enumerate(queries,1):
        sid=args.case+('-new-'+str(number) if args.case=='memory' else '-session')
        before=0
        if (state/'history.db').exists():
            with sqlite3.connect(state/'history.db') as db:before=db.execute('select coalesce(max(id),0) from history').fetchone()[0]
        flags=['--engine',args.engine,'--loop','-y','--max-turns','8','--timeout','300','--exec-timeout','180','--session',sid]
        if args.case not in ('web_search','web_fetch'):flags.append('--no-web')
        if args.case=='files':flags+=['--file',fixtures['file']]
        sys.argv=[str(ROOT/'launch.py'),'harness.py',*flags,'--',query]
        start=time.monotonic();code=launch.main()
        with sqlite3.connect(state/'history.db') as db:
            db.row_factory=sqlite3.Row;rows=[dict(r) for r in db.execute('select * from history where id>? and session_id=? order by id',(before,sid))]
        runs.append({'query':query,'exit_code':code,'seconds':round(time.monotonic()-start,2),'rows':rows})
        if code:break
    events=[]
    if (state/'usage.jsonl').exists():events=[json.loads(line) for line in (state/'usage.jsonl').read_text().splitlines()]
    uses=[r for run in runs for row in run['rows'] for r in json.loads(row.get('api_tool_uses_json') or '[]')]
    success=all(run['exit_code']==0 for run in runs) and len(runs)==len(queries)
    if args.case in ('web_search','web_fetch'):
        key='search' if args.case=='web_search' else 'fetch'
        success=success and any(json.loads(row.get('lookup_counts_json') or '{}').get(key,0)>0 for run in runs for row in run['rows'])
    elif args.case=='history_cache':
        success=success and runs[2]['rows'][-1]['cache_read_tokens']>runs[0]['rows'][-1]['input_tokens'] and marker in runs[2]['rows'][-1]['direct_answer']
    else:success=success and any(r['tool']==args.case and r['status']=='success' for r in uses)
    if args.case=='memory' and len(runs)==2:success=success and marker in runs[-1]['rows'][-1]['direct_answer']
    if args.case=='files':success=success and fixtures['sentence'] in runs[-1]['rows'][-1]['direct_answer']
    if args.case=='skills' and options.get('expected_skill_marker'):success=success and options['expected_skill_marker'] in runs[-1]['rows'][-1]['direct_answer']
    if args.case=='file_search' and options.get('expected_file_marker'):success=success and options['expected_file_marker'] in runs[-1]['rows'][-1]['direct_answer']
    if args.case in ('apply_patch','text_editor'):success=success and (state/'edit-proof.txt').read_text()=='orange\n'
    report={'engine':args.engine,'tool':args.case,'passed':bool(success),'marker':marker,'runs':runs,'events':events,'commands':commands}
    write_json(state/'report.json',report)
    print(json.dumps({'engine':args.engine,'tool':args.case,'passed':bool(success),'exit_codes':[r['exit_code'] for r in runs],'report':str(state/'report.json')}),file=sys.stderr)
    return 0 if success else 1


if __name__=='__main__':raise SystemExit(main())
