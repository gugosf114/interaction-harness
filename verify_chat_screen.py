#!/data/data/com.termux/files/usr/bin/python
"""Real Termux PTY proof of the chat screen; private state and provider receipts."""
import argparse
import errno
import fcntl
import json
import os
from pathlib import Path
import pty
import re
import select
import signal
import sqlite3
import struct
import subprocess
import termios
import time

ROOT=Path(__file__).resolve().parent
ANSI=re.compile(rb'\x1b\[[0-?]*[ -/]*[@-~]')

class Terminal:
    def __init__(self, engine, state, log, session='screen-proof'):
        self.pid,self.fd=pty.fork()
        if self.pid==0:
            env=os.environ.copy();env.pop('LD_LIBRARY_PATH',None)
            env.pop('NO_COLOR',None)
            env.update(HARNESS_STATE_DIR=str(state),TERM='xterm-256color')
            os.execve(str(ROOT/'harness'),[str(ROOT/'harness'),'--chat','--loop','-y','--engine',engine,'--effort','max','--session',session],env)
        fcntl.ioctl(self.fd,termios.TIOCSWINSZ,struct.pack('HHHH',50,110,0,0))
        self.log=log.open('wb');self.pending=b'';self.full=bytearray();self.closed=False
    def send(self,text):os.write(self.fd,text.encode())
    def read(self,timeout=.2):
        if not select.select([self.fd],[],[],timeout)[0]:return b''
        try:block=os.read(self.fd,65536)
        except OSError as exc:
            if exc.errno==errno.EIO:self.closed=True;return b''
            raise
        if not block:self.closed=True;return b''
        self.log.write(block);self.log.flush();self.full.extend(block);self.pending+=block
        return block
    def prompt(self,timeout=7200):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            self.read()
            if self.closed:raise RuntimeError('Chat closed before its prompt.')
            if ANSI.sub(b'',self.pending).replace(b'\r',b'').endswith(b'> '):
                result=self.pending;self.pending=b'';return result
        raise RuntimeError('Proof did not receive a prompt within two hours.')
    def close(self):
        self.send('quit\n')
        while not self.closed:self.read()
        _,status=os.waitpid(self.pid,0);os.close(self.fd);self.log.close()
        return os.waitstatus_to_exitcode(status)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--engine',choices=['openai','anthropic'],required=True)
    parser.add_argument('--state',type=Path,required=True);args=parser.parse_args()
    state=args.state.resolve();state.mkdir(parents=True,exist_ok=True,mode=0o700)
    (state/'mods.json').write_text(json.dumps({k:False for k in ('voice','proof','tree','narrator','memory-version','reindex','voiceline')})+'\n')
    # The working reply and judge gates stay on. A fixture-only note search adds no value.
    marker='blue-lantern-'+args.engine
    paste='Reply with the first and last labels from this block: label01.\n'+'\n'.join('label'+str(i).zfill(2) for i in range(2,13))
    lines=[f'The chat-screen proof word is {marker}. Reply with just that word.',
           'What is the chat-screen proof word? Reply with just that word.',paste]
    term=Terminal(args.engine,state,state/'terminal.log')
    term.prompt();print('prompt ready',flush=True)
    for i,line in enumerate(lines):
        term.send(('\x1b[200~'+line+'\x1b[201~' if '\n' in line else line)+'\n')
        term.prompt();print('turn '+str(i+1)+' complete',flush=True)
    other='claude-opus-5-5' if args.engine=='openai' else 'gpt-6.1-sol'
    term.send('/model '+other+'\n');term.prompt()
    term.send('What is the chat-screen proof word? Reply with just that word.\n');term.prompt();print('lane switch complete',flush=True)
    term.send('Work out every prime between one and one million, then give their sum.\n')
    end=time.monotonic()+5
    while time.monotonic()<end:term.read()
    term.send('\x03');interrupted=term.prompt();print('interrupt returned to prompt',flush=True)
    term.send('Reply with the chat-screen proof word again.\n');term.prompt()
    term.send('/copy\n');copied=term.prompt()
    env=os.environ.copy();env.pop('LD_LIBRARY_PATH',None)
    clip=subprocess.run(['termux-clipboard-get'],capture_output=True,text=True,env=env,timeout=40)
    (state/'clipboard.txt').write_text(clip.stdout)
    saved=state/'saved-answer.txt';term.send('/save '+str(saved)+'\n');term.prompt()
    for line in ('/cost','/status','/help'):
        term.send(line+'\n');term.prompt()
    code=term.close()
    db=sqlite3.connect(state/'history.db');db.row_factory=sqlite3.Row
    rows=[dict(x) for x in db.execute('SELECT * FROM history ORDER BY id')];db.close()
    accepted=[r for r in rows if r['status']=='accepted']
    statuses=[json.loads(x) for x in (state/'chat-status.jsonl').read_text().splitlines()]
    from storage import request_metrics
    checks={
      'exit_zero':code==0, 'three_turns_first_lane':len(accepted)>=3 and all(r['engine']==args.engine for r in accepted[:3]),
      'paste_whole':len(paste.splitlines())==12 and sum(r['raw_input']==paste for r in rows)==1,
      'switch_keeps_memory':len(accepted)==5 and accepted[3]['engine']!=args.engine and marker in accepted[3]['direct_answer'],
      'ctrl_c_keeps_chat':b'Stopped.' in interrupted and any(r['status']=='interrupted' for r in rows) and len(accepted)==5,
      'clipboard_matches':clip.returncode==0 and clip.stdout.rstrip('\n')==accepted[-1]['direct_answer'] and b'Copied the last answer.' in copied,
      'save_matches':saved.read_text().rstrip('\n')==accepted[-1]['direct_answer'],
      'status_per_reply':len(statuses)==len(accepted),
      'status_usage_matches_db':len(statuses)==len(accepted) and all(all(request_metrics(s['events'])[k]==r[k] for k in ('input_tokens','output_tokens','cache_read_tokens')) for s,r in zip(statuses,accepted)),
      'color_in_terminal':b'\x1b[96m' in term.full and b'\x1b[97m' in term.full,
      'max_effort':all(s['effort']=='max' for s in statuses),
      'private_thinking_absent':b'thinking_delta' not in term.full,
    }
    # Start a new process and use the real up arrow. Persisted history contains whole messages.
    again=Terminal(args.engine,state,state/'history-terminal.log',session='screen-proof')
    again.prompt();again.send('\x1b[A\n');again.prompt();history_code=again.close()
    db=sqlite3.connect(state/'history.db');last=db.execute("SELECT raw_input FROM history WHERE session_id='screen-proof' ORDER BY id DESC LIMIT 1").fetchone();db.close()
    checks['history_across_launches']=history_code==0 and last and last[0]=='Reply with the chat-screen proof word again.'
    result={'engine':args.engine,'exit_code':code,'history_exit_code':history_code,'clipboard_exit_code':clip.returncode,'checks':checks,'all_passed':all(checks.values()),'status_records':statuses,'rows':[{k:r[k] for k in ('id','engine','model','session_id','status','raw_input','direct_answer','input_tokens','output_tokens','cache_read_tokens')} for r in rows]}
    (state/'report.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'all_passed':result['all_passed'],'checks':checks,'exit_code':code,'report':str(state/'report.json')}),flush=True)
    return 0 if result['all_passed'] else 1

if __name__=='__main__':raise SystemExit(main())
