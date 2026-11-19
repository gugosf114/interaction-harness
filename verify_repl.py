#!/data/data/com.termux/files/usr/bin/python
"""Live tests of the real Bash aliases, interactive PTYs and one-off mode."""
import argparse
from datetime import datetime, timezone
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
from verify_quiet import quiet, turn_events

ROOT=Path(__file__).resolve().parent
BASH='/data/data/com.termux/files/usr/bin/bash'


def terminal(command,env,lines=(),timeout=600):
    pid,master=pty.fork()
    if pid==0:
        os.execve(BASH,[BASH,'--noprofile','--rcfile',str(Path.home()/'.bashrc'),'-ic',command],env)
    output=bytearray(); pending=b''; sent=0; deadline=time.monotonic()+timeout; timed_out=False
    try:
        while time.monotonic()<deadline:
            if not select.select([master],[],[],0.2)[0]: continue
            try: block=os.read(master,65536)
            except OSError as exc:
                if exc.errno==errno.EIO: break
                raise
            if not block: break
            output.extend(block);pending+=block
            if lines and pending.endswith(b'> ') and sent<len(lines):
                os.write(master,(lines[sent]+'\n').encode());sent+=1;pending=b''
        else:
            timed_out=True;os.killpg(pid,signal.SIGKILL)
    finally:
        os.close(master);_,status=os.waitpid(pid,0)
    code=os.waitstatus_to_exitcode(status)
    return {'exit_code':code,'timed_out':timed_out,'sent_lines':sent,'transcript':output.decode(errors='replace')}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine',choices=['openai','anthropic'],required=True)
    args=parser.parse_args()
    alias='g1' if args.engine=='openai' else 'g2'
    model='gpt-6.1-sol' if args.engine=='openai' else 'claude-opus-5-5'
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    folder=ROOT/'state'/'repl-checks'/(stamp+'-'+args.engine+'-'+uuid.uuid4().hex[:6])
    folder.mkdir(parents=True,mode=0o700)
    runtime=quiet(folder/'runtime')  # the verifier's answers are not read aloud
    env=os.environ.copy();env.pop('LD_LIBRARY_PATH',None);env['HARNESS_STATE_DIR']=str(runtime)
    oneoff_marker='oneshot-'+uuid.uuid4().hex[:8]
    print('Checking '+alias+' one-off mode.',flush=True)
    oneoff=terminal(alias+' '+shlex.quote('Reply with exactly '+oneoff_marker+'. This is a text-only response.'),env,timeout=240)
    (folder/'oneoff-terminal.txt').write_text(oneoff['transcript'])
    marker='orbit-'+uuid.uuid4().hex[:8]
    print('Checking '+alias+' interactive memory and exit.',flush=True)
    interactive=terminal(alias,env,[f'The session marker is {marker}. State the marker back.','What is the session marker?', 'quit' if args.engine=='openai' else 'exit'])
    (folder/'chat-terminal.txt').write_text(interactive['transcript'])
    db=sqlite3.connect(runtime/'history.db');db.row_factory=sqlite3.Row
    try: rows=[dict(r) for r in db.execute('SELECT * FROM history ORDER BY id')]
    finally: db.close()
    usage_path=runtime/'usage.jsonl'
    events=turn_events([json.loads(line) for line in usage_path.read_text().splitlines()] if usage_path.exists() else [])  # model turns only
    checks={
      'oneoff_exits':oneoff['exit_code']==0 and not oneoff['timed_out'],
      'oneoff_answer':bool(rows) and oneoff_marker in (rows[0].get('direct_answer') or ''),
      'interactive_exits':interactive['exit_code']==0 and not interactive['timed_out'] and interactive['sent_lines']==3,
      'three_successful_turns':len(rows)==3 and all(row['status']=='accepted' for row in rows),
      'memory':len(rows)==3 and marker in (rows[2].get('direct_answer') or ''),
      'one_session_inside_chat':len(rows)==3 and rows[1]['session_id']==rows[2]['session_id'] and rows[0]['session_id']!=rows[1]['session_id'],
      'correct_engine_and_model':bool(rows) and all(row['engine']==args.engine and row['model']==model for row in rows),
      'actual_model_returned':bool(events) and all(event.get('model_returned')==model for event in events),
      'max_effort':bool(events) and all(event.get('effort')=='max' for event in events),  # the aliases run --effort max
    }
    cache=[(event.get('usage') or {}).get('cache_read_input_tokens',0)+((event.get('usage') or {}).get('input_tokens_details') or {}).get('cached_tokens',0) for event in events]
    checks['cache_reused']=any(cache)
    report={'time_utc':stamp,'engine':args.engine,'alias':alias,'model':model,'effort':'max',
            'all_passed':all(checks.values()),'checks':checks,'cache_read_tokens':cache,
            'oneoff':oneoff,'interactive':interactive,'rows':[{'id':row['id'],'session_id':row['session_id'],'answer':row['direct_answer'],'status':row['status']} for row in rows]}
    path=folder/'report.json';path.write_text(json.dumps(report,indent=2)+'\n');path.chmod(0o600)
    (ROOT/'state'/('latest-repl-'+args.engine+'-report.txt')).write_text(str(path)+'\n')
    print(json.dumps({'all_passed':report['all_passed'],'checks':checks,'cache_read_tokens':cache}))
    print('Report: '+str(path))
    return 0 if report['all_passed'] else 1


if __name__=='__main__':raise SystemExit(main())
