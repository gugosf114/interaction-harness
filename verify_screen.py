#!/data/data/com.termux/files/usr/bin/python
"""Live proof through the real launcher, with hidden-only input for this test.

Start a hidden display first. This verifier never creates, launches or stops one.
It saves API rows and command receipts under its isolated --state directory.
"""
import argparse
import json
import os
from pathlib import Path
import shlex
import sqlite3
import sys
import time

import launch
from native_tools import handle

ROOT = Path(__file__).resolve().parent


def allowed(command, hidden):
    """Proof-only allowlist. Never grant a live model visible-screen input."""
    lex=shlex.shlex(command,posix=True,punctuation_chars=';&|<>\n')
    lex.whitespace=' \t\r';lex.whitespace_split=True;lex.commenters=''
    groups=[[]]
    for part in lex:
        if part in (';', '&&') or part and set(part)=={'\n'}: groups.append([])
        elif any(c in part for c in ('`','\n','\r')) or '$(' in part: return False
        elif part in ('&','|','||','>','>>','<','<<'): return False
        else: groups[-1].append(part)
    groups=[args for args in groups if args]
    if not groups:return False
    for args in groups:
        if args in (['card','screen'], ['card','phone'], ['cards']): continue
        if args[0]=='sleep' and len(args)==2:
            try:
                if 0<=float(args[1])<=3: continue
            except ValueError: pass
            return False
        if args[0]!='screen' or len(args)<2: return False
        verb=args[1]
        if verb not in ('snap','size','tap','swipe','text','key'): return False
        target='phone';values=[];i=2
        while i<len(args):
            if args[i]=='--target' and i+1<len(args): target=args[i+1];i+=2
            elif args[i].startswith('--target='): target=args[i].split('=',1)[1];i+=1
            # Proof uses unique default paths, so no model-controlled filesystem writes.
            elif args[i].startswith('--'): return False
            else: values.append(args[i]);i+=1
        if target=='phone':
            if verb not in ('snap','size') or values: return False
        elif target != 'hidden:'+hidden: return False
    return True


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine',choices=['openai','anthropic'],required=True)
    parser.add_argument('--case',choices=['app','search','phone','cache'],required=True)
    parser.add_argument('--hidden',default='astra-screen-proof')
    parser.add_argument('--state',type=Path,required=True)
    parser.add_argument('--key-dir',type=Path,default=Path.home()/'interaction-harness/state')
    args=parser.parse_args()
    state=args.state.resolve();state.mkdir(parents=True,exist_ok=True,mode=0o700)
    name='OPENAI_API_KEY' if args.engine=='openai' else 'ANTHROPIC_API_KEY'
    if not os.environ.get(name):
        os.environ[name]=(args.key_dir/('api-key' if args.engine=='openai' else 'anthropic-api-key')).read_text().strip()
    os.environ['HARNESS_STATE_DIR']=str(state)
    questions={
        'app':f'Take a picture of hidden screen {args.hidden} and tell me what app is showing.',
        'search':f'Find the search box on hidden screen {args.hidden}, tap it, type wifi, and tell me the first result. Capture the screen before choosing coordinates and capture it again after typing. Leave it on the result list.',
        'phone':'Take a picture of my phone screen and tell me the time shown in the status bar. Capture only.',
        'cache':'What app did the saved picture of the hidden screen show? Use the picture already in this chat.'}
    query=questions[args.case]
    db_path=state/'history.db';before=0
    if db_path.exists():
        with sqlite3.connect(db_path) as db:before=db.execute('SELECT coalesce(max(id),0) FROM history').fetchone()[0]
    commands=[]
    def checked(request):
        if request.get('op')!='exec' or not allowed(request.get('command',''),args.hidden):
            result={'error':'This screen proof permits only card reads, captures, and input on its hidden screen.'}
        else: result=handle(request)
        commands.append({'request':request,'result':result})
        (state/(args.case+'-commands.json')).write_text(json.dumps(commands,indent=2))
        return result
    launch.handle=checked
    session_name='screen-app' if args.case in ('app','cache') else 'screen-'+args.case
    sys.argv=[str(ROOT/'launch.py'),'harness.py','--engine',args.engine,'--loop','-y','--no-web',
              '--max-turns','14','--exec-timeout','180','--timeout','300','--session',
              session_name,'--',query]
    start=time.monotonic();code=launch.main()
    with sqlite3.connect(db_path) as db:
        db.row_factory=sqlite3.Row
        rows=[dict(r) for r in db.execute('SELECT * FROM history WHERE id>? AND session_id=? ORDER BY id',(before,session_name))]
    report={'engine':args.engine,'case':args.case,'query':query,'exit_code':code,
            'elapsed_seconds':round(time.monotonic()-start,2),'rows':rows,'commands':commands}
    (state/(args.case+'-report.json')).write_text(json.dumps(report,indent=2))
    print(json.dumps({k:report[k] for k in ('engine','case','exit_code','elapsed_seconds')}),file=sys.stderr)
    return code


if __name__=='__main__':raise SystemExit(main())
