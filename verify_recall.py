#!/usr/bin/env python3
"""Private live recall proof through the real launcher, gates and native bridge.

The worker only records provider request arguments, excluding credentials. No response/private
thinking is recorded. Use --engine openai|anthropic --state DIR [--session NAME] [--chat] TEXT.
"""
import argparse
import json
import os
from pathlib import Path
import runpy
import sys

ROOT=Path(__file__).resolve().parent


def worker():
    import functools
    import openai.resources.responses.responses as oai
    import anthropic.resources.messages.messages as ant
    def instrument(cls,name,provider):
        original=getattr(cls,name)
        @functools.wraps(original)
        def recorded(self,*args,**kwargs):
            state=Path(os.environ['HARNESS_STATE_DIR'])
            path=state/'request-capture.jsonl'
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
            with os.fdopen(fd,'a') as out:
                out.write(json.dumps({'provider':provider,'method':name,'request':kwargs},default=str,ensure_ascii=False)+'\n')
            return original(self,*args,**kwargs)
        setattr(cls,name,recorded)
    instrument(oai.Responses,'create','openai')
    instrument(oai.Responses,'stream','openai')
    instrument(ant.Messages,'create','anthropic')
    instrument(ant.Messages,'stream','anthropic')
    sys.argv=[str(ROOT/'bootstrap.py'),*sys.argv[2:]]
    runpy.run_path(str(ROOT/'bootstrap.py'),run_name='__main__')


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--engine',required=True,choices=['openai','anthropic'])
    p.add_argument('--state',required=True,type=Path)
    p.add_argument('--session')
    p.add_argument('--chat',action='store_true')
    p.add_argument('text',nargs='*')
    args=p.parse_args()
    state=args.state.resolve();state.mkdir(parents=True,exist_ok=True,mode=0o700)
    if not (state/'mods.json').exists():
        (state/'mods.json').write_text(json.dumps({'memory-version':False,'voice':False}))
    os.environ['HARNESS_STATE_DIR']=str(state)
    os.environ.pop('LD_LIBRARY_PATH',None)
    import launch
    original=launch.subprocess.Popen
    def start(command,*pargs,**kwargs):
        command=list(command)
        if str(ROOT/'bootstrap.py') in command:
            i=command.index(str(ROOT/'bootstrap.py'))
            command[i:i+1]=[str(Path(__file__).resolve()),'--worker']
        return original(command,*pargs,**kwargs)
    launch.subprocess.Popen=start
    options=['--engine',args.engine,'--effort','max','--timeout','3600','--loop','-y']
    if args.session:options+=['--session',args.session]
    if args.chat:options+=['--chat']
    sys.argv=['launch.py','harness.py',*options,*args.text]
    return launch.main()


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--worker':worker()
    else:raise SystemExit(main())
