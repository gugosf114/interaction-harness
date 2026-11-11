"""Native Termux operations served by the launcher; no SDK or Debian execution."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile

PREFIX = '/data/data/com.termux/files/usr'
OUTPUT_LIMIT = 1048576


def run_bounded(command, timeout=120):
    env = os.environ.copy()
    env.pop('LD_LIBRARY_PATH', None)
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                   env=env, start_new_session=True)
        timed_out = False
        try: code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL); process.wait(); code=124
        except BaseException:
            os.killpg(process.pid,signal.SIGKILL); process.wait(); raise
        out.seek(0); err.seek(0)
        output, error = out.read(OUTPUT_LIMIT+1), err.read(OUTPUT_LIMIT+1)
        truncated = len(output)>OUTPUT_LIMIT or len(error)>OUTPUT_LIMIT
        return {'exit_code':code,'stdout':output[:OUTPUT_LIMIT].decode(errors='replace'),
                'stderr':error[:OUTPUT_LIMIT].decode(errors='replace'),
                'timed_out':timed_out,'truncated':truncated}


def confirm():
    try:
        with open('/dev/tty','r') as reader, open('/dev/tty','w') as writer:
            writer.write('[Run command? (y/N)]: '); writer.flush()
            return reader.readline().strip().lower() == 'y'
    except OSError:
        return None


def handle(request):
    operation = request.get('op')
    if operation == 'exec':
        command = request.get('command')
        if not isinstance(command,str) or not command.strip() or '\x00' in command:
            return {'error':'Invalid command payload.'}
        approved = True if request.get('auto_confirm') is True else confirm()
        if approved is None: return {'error':'Command approval requires an interactive Termux terminal.'}
        if not approved: return {'approved':False,'exit_code':0,'stdout':'','stderr':''}
        result = run_bounded([PREFIX+'/bin/bash','--noprofile','--norc','-c',command],
                             timeout=max(1,min(600,int(request.get('timeout',120)))))
        return {'approved':True, **result}
    if operation == 'listen':
        binary = shutil.which('termux-speech-to-text')
        if not binary: return {'error':'Install Termux:API and its termux-api package to use --listen.'}
        result = run_bounded([binary], timeout=max(1,min(180,int(request.get('timeout',90)))))
        if result['timed_out']: return {'error':'Dictation timed out.'}
        text = result['stdout'].strip()
        if result['exit_code'] or not text:
            return {'error':'Android returned no dictation. Check Termux:API microphone access.'}
        try:
            value=json.loads(text)
            if isinstance(value,dict) and 'error' in value: return {'error':'Android speech recognition failed.'}
        except ValueError: pass
        return {'text':text}
    return {'error':'Unknown native operation.'}
