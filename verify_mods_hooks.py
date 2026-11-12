#!/usr/bin/env python3
"""Real launcher proof. A named check can replace the first answer with a documented bad fixture.

The provider, corrective retry, every gate, judge, command bridge and hooks still run.
Only memory's source is a scratch folder. Private request captures contain no keys or thinking.
"""
import argparse
import json
import os
from pathlib import Path
import runpy
import sys

ROOT=Path(__file__).resolve().parent
QUESTIONS={
    'length':'Is two plus two four?',
    'plain-words':'Explain why a gate keeps a dog in a yard.',
    'receipts':'For this check, use no tools and read no files. Say only GUESS if you have not read WiM source.',
    'no-background':'Print the word foreground using printf.',
}


def worker():
    import functools
    with os.fdopen(int(sys.argv[2])) as stream:
        values=json.load(stream)
    os.environ.update({key:value for key,value in values.items() if isinstance(value,str)})
    os.environ['HARNESS_BRIDGE_FD']=sys.argv[3]
    import harness as h
    saved_root=h.ROOT
    try:
        h.ROOT=Path('/data/data/com.termux/files/home/interaction-harness')
        for engine,name in [('openai','OPENAI_API_KEY'),('anthropic','ANTHROPIC_API_KEY')]:
            os.environ[name]=h.load_key(engine)
    finally:
        h.ROOT=saved_root
    import memory_versions
    import reply_judge
    import helper_model
    state=Path(os.environ['HARNESS_STATE_DIR'])
    memory_versions.SOURCE=state/'memory-fixture'
    plan=json.loads((state/'proof-plan.json').read_text())
    from senses import TurnSenses
    original=TurnSenses.send
    seen=set()
    def write(name,data):
        with (state/name).open('a') as stream: stream.write(json.dumps(data,ensure_ascii=False,default=str)+'\n')
    def planted(self,client,**kw):
        response=original(self,client,**kw)
        raw_input=next((message.get('content') for message in reversed(kw['messages'])
                        if message.get('role')=='user' and message.get('content') in QUESTIONS.values()),None)
        kind=next((key for key,question in QUESTIONS.items() if raw_input==question),None)
        if plan['case']=='checks' and kind and kind not in seen:
            seen.add(kind)
            data={'intent':'observation','cleaned_input':raw_input,'direct_answer':'Yes.','execution_payload':None}
            if kind=='length':data['direct_answer']='Yes. '+'The cat sat on the mat. '*30
            if kind=='plain-words':data['direct_answer']=('The idempotent configuration facilitates deterministic orchestration of asynchronous serialization across heterogeneous infrastructure, guaranteeing reproducible provenance for subsequent invocations. '*2)
            if kind=='receipts':data['direct_answer']='WiM sends the text by itself.'
            if kind=='no-background':data.update(intent='action_request',direct_answer='Printing the word.',execution_payload='nohup printf foreground &')
            write('planted.jsonl',{'case':kind,'reply':data})
            response=response.model_copy(deep=True)
            if self.engine=='openai':
                for item in response.output:
                    if getattr(item,'type',None)=='message':
                        for content in item.content:
                            if getattr(content,'type',None)=='output_text':content.text=json.dumps(data)
            else:
                for content in response.content:
                    if getattr(content,'type',None)=='tool_use' and content.name=='emit_reply':content.input=data
        return response
    TurnSenses.send=planted
    ask=reply_judge.ask
    def record_judge(packet,**kw):
        write('judge-packets.jsonl',{'packet':json.loads(packet)})
        result=ask(packet,**kw)
        write('judge-results.jsonl',result)
        return result
    reply_judge.ask=record_judge
    complete=helper_model.complete
    def record_helper(engine,kind,system,prompt,**kw):
        result=complete(engine,kind,system,prompt,**kw)
        write('helper-results.jsonl',{'engine':engine,'kind':kind,'prompt':prompt,'result':result})
        return result
    helper_model.complete=record_helper
    import openai.resources.responses.responses as oai
    import anthropic.resources.messages.messages as ant
    def instrument(cls,name,provider):
        method=getattr(cls,name)
        @functools.wraps(method)
        def capture(self,*args,**kwargs):
            write('request-capture.jsonl',{'provider':provider,'method':name,'request':kwargs})
            return method(self,*args,**kwargs)
        setattr(cls,name,capture)
    for name in ('create','stream'):
        instrument(oai.Responses,name,'openai');instrument(ant.Messages,name,'anthropic')
    sys.argv=[str(ROOT/'harness.py'),*sys.argv[5:]]
    runpy.run_path(str(ROOT/'harness.py'),run_name='__main__')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--engine',choices=['openai','anthropic'],required=True)
    parser.add_argument('--case',choices=['checks','tree','proof','both','autopilot'],required=True)
    parser.add_argument('--state',type=Path,required=True)
    parser.add_argument('--check',choices=list(QUESTIONS))
    args=parser.parse_args()
    state=args.state.resolve();state.mkdir(parents=True,exist_ok=True,mode=0o700)
    (state/'proof-plan.json').write_text(json.dumps({'case':args.case,'engine':args.engine}))
    (state/'memory-fixture').mkdir(exist_ok=True)
    (state/'memory-fixture/note.md').write_text('Scratch note: blue shelf.\n')
    if not (state/'tools.json').exists() and (ROOT/'state/tools.json').exists():
        import shutil
        shutil.copy2(ROOT/'state/tools.json',state/'tools.json')
    os.environ['HARNESS_STATE_DIR']=str(state)
    os.environ.pop('LD_LIBRARY_PATH',None)
    if args.case=='autopilot':
        import subprocess
        subprocess.run(['git','init','-q','--initial-branch=proof',str(state)],check=True)
        os.chdir(state)
    import launch
    popen=launch.subprocess.Popen
    def start(command,*pargs,**kwargs):
        command=list(command)
        if str(ROOT/'bootstrap.py') in command:
            index=command.index(str(ROOT/'bootstrap.py'))
            command[index:index+1]=[str(Path(__file__).resolve()),'--worker']
        return popen(command,*pargs,**kwargs)
    launch.subprocess.Popen=start
    options=['--engine',args.engine,'--effort','max','--timeout','3600','--loop','-y','--session','mods-proof']
    if args.case=='checks':
        questions=[QUESTIONS[args.check]] if args.check else list(QUESTIONS.values())
        text='\n'.join([*questions,'/mods','quit'])+'\n';options+=['--chat']
    elif args.case=='tree':
        text='\n'.join(['Let us plan a loaf of bread. Start with flour.',
                        'Inside that loaf plan, focus on yeast. What does yeast do?',
                        'Inside that yeast step, focus on warm water. Why use warm water?',
                        '/where','/up','/where','quit'])+'\n';options+=['--chat']
    elif args.case=='proof':
        text='Use the local harness_command tool to run printf mods-hook-proof. Then say what it printed.'
    elif args.case=='both':
        text='What is two plus two? Answer in one short sentence.'
        options=['--both','--lanes','openai,anthropic','--effort','max','--timeout','3600','--session','both-mods']
    else:
        text=f'/autopilot Write one sentence about a blue shelf to {state}/shelf.txt. Read it back. Then finish.\n/autopilot status\nquit\n'
        options+=['--chat']
    # A real stdin pipe, consumed by the normal native launcher.
    import tempfile
    with tempfile.TemporaryFile(mode='w+') as stream:
        stream.write(text);stream.seek(0)
        original=os.dup(0)
        try:
            os.dup2(stream.fileno(),0)
            sys.argv=['launch.py','harness.py',*options]
            return launch.main()
        finally:
            os.dup2(original,0);os.close(original)


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--worker':worker()
    else:raise SystemExit(main())
