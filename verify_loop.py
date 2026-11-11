#!/data/data/com.termux/files/usr/bin/python
"""Live create/read loop through the real aliases and native Termux bridge."""
import argparse
from datetime import datetime,timezone
import errno
import json
import os
from pathlib import Path
import pty
import select
import shlex
import signal
import sqlite3
import time
import uuid

ROOT=Path(__file__).resolve().parent
BASH='/data/data/com.termux/files/usr/bin/bash'
PROMPT=b'[Run command? (y/N)]: '


def run_terminal(command,env,database,expected,auto):
    pid,master=pty.fork()
    if pid==0:
        os.execve(BASH,[BASH,'--noprofile','--rcfile',str(Path.home()/'.bashrc'),'-ic',command],env)
    output=bytearray();pending=b'';decisions=[];deadline=time.monotonic()+400;timed_out=False
    try:
        while time.monotonic()<deadline:
            if not select.select([master],[],[],0.2)[0]:continue
            try:block=os.read(master,65536)
            except OSError as exc:
                if exc.errno==errno.EIO:break
                raise
            if not block:break
            output.extend(block);pending+=block
            if pending.endswith(PROMPT):
                db=sqlite3.connect(database)
                try:payload=db.execute('SELECT execution_payload FROM history ORDER BY id DESC LIMIT 1').fetchone()[0]
                finally:db.close()
                ok=not auto and len(decisions)<len(expected) and payload.strip()==expected[len(decisions)]
                decisions.append({'command':payload,'approved':ok})
                os.write(master,b'y\n' if ok else b'n\n');pending=b''
        else:
            timed_out=True;os.killpg(pid,signal.SIGKILL)
    finally:
        os.close(master);_,status=os.waitpid(pid,0)
    return {'exit_code':os.waitstatus_to_exitcode(status),'timed_out':timed_out,
            'confirmation_decisions':decisions,'transcript':output.decode(errors='replace')}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine',choices=['openai','anthropic'],required=True)
    parser.add_argument('--yes',action='store_true',help='Test explicit -y mode instead of per-command approval.')
    args=parser.parse_args()
    folder=ROOT/'state'/'loop-checks'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+args.engine+'-'+uuid.uuid4().hex[:6])
    folder.mkdir(parents=True,mode=0o700);runtime=folder/'runtime';target=folder/'roundtrip.txt'
    marker='loop-proof-'+uuid.uuid4().hex[:12]
    commands=["printf '%s\\n' "+shlex.quote(marker)+' > '+shlex.quote(str(target)), 'cat -- '+shlex.quote(str(target))]
    query=('Perform a two-step verification. In the first model turn, propose exactly this command: '+commands[0]+
           '\nAfter receiving its execution observation, in the second turn propose exactly this command: '+commands[1]+
           '\nAfter receiving the read result, give a final answer containing the observed marker with execution_payload null. '
           'Use two separate command payloads. Do not combine steps or run extra commands.')
    alias='g1' if args.engine=='openai' else 'george'
    command=alias+' --loop --max-turns 5 '+('--yes ' if args.yes else '')+shlex.quote(query)
    env=os.environ.copy();env.pop('LD_LIBRARY_PATH',None);env['HARNESS_STATE_DIR']=str(runtime)
    started=time.monotonic();run=run_terminal(command,env,runtime/'history.db',commands,args.yes)
    rows=[]
    if (runtime/'history.db').exists():
        db=sqlite3.connect(runtime/'history.db');db.row_factory=sqlite3.Row
        try:rows=[dict(r) for r in db.execute('SELECT * FROM history ORDER BY id')]
        finally:db.close()
    executed=[r for r in rows if r['execution_result'] is not None]
    results=[json.loads(r['execution_result']) for r in executed]
    sessions=[]
    if rows:
        session=runtime/'sessions'/(rows[0]['session_id']+'.json')
        if session.exists():sessions=json.loads(session.read_text())['turns']
    checks={
        'exit_zero':run['exit_code']==0 and not run['timed_out'],
        'three_model_turns':len(rows)==3 and all(r['status']=='accepted' for r in rows),
        'two_exact_commands':[r['execution_payload'] for r in executed]==commands,
        'commands_approved_and_successful':len(results)==2 and all(r['approved'] is True and r['exit_code']==0 for r in results),
        'read_feedback':len(results)==2 and results[1]['stdout']==marker+'\n',
        'file_contents':target.exists() and target.read_text()==marker+'\n',
        'final_answer':bool(rows) and rows[-1]['execution_payload'] is None and marker in (rows[-1]['direct_answer'] or ''),
        'same_session':len({r['session_id'] for r in rows})==1,
        'four_field_replies':bool(sessions) and all(set(s['reply'])=={'intent','cleaned_input','direct_answer','execution_payload'} for s in sessions),
        'approval_mode':not run['confirmation_decisions'] if args.yes else len(run['confirmation_decisions'])==2 and all(d['approved'] for d in run['confirmation_decisions']),
        'latency_recorded':bool(rows) and all(r['latency_ms'] is not None and r['latency_ms']>0 for r in rows),
    }
    report={'engine':args.engine,'auto_confirm':args.yes,'marker':marker,'target_file':str(target),
            'sqlite_database':str(runtime/'history.db'),'wall_ms':round((time.monotonic()-started)*1000),
            'checks':checks,'all_passed':all(checks.values()),'run':run,'rows':rows}
    path=folder/'report.json';path.write_text(json.dumps(report,indent=2)+'\n');path.chmod(0o600)
    (ROOT/'state'/('latest-loop-'+args.engine+'.txt')).write_text(str(path)+'\n')
    print(json.dumps({'report':str(path),'all_passed':report['all_passed'],'checks':checks}),flush=True)
    return 0 if report['all_passed'] else 1


if __name__=='__main__':raise SystemExit(main())
