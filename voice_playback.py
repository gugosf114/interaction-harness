"""Native-owned speech worker: the prompt stays open and one-off PRoot exit cannot cut speech."""
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
import mod_switches
import speech_lock

ROOT=Path(__file__).resolve().parent
PREFIX='/data/data/com.termux/files/usr'
SAY='/usr/local/bin/say'


def record(state,voice_id,status,**fields):
    path=Path(state)/'usage.jsonl';path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    event={'time_utc':datetime.now(timezone.utc).isoformat(),'kind':'hook:voice','voice_id':voice_id,'status':status,**fields}
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
    with os.fdopen(fd,'a') as stream:stream.write(json.dumps(event,ensure_ascii=False)+'\n')
    return event


def enqueue(text,state,generation=0):
    """Called by the native bridge, outside the current request's PRoot process."""
    if not isinstance(text,str) or not text.strip() or not isinstance(state,str) or not state or type(generation) is not int or generation<0:
        return {'error':'Invalid speech request.'}
    voice_id=uuid.uuid4().hex
    env=dict(os.environ);env.pop('LD_LIBRARY_PATH',None)
    child=subprocess.Popen([PREFIX+'/bin/proot-distro','login','debian','--',str(ROOT/'.venv/bin/python'),
                            '-B',str(ROOT/'voice_playback.py'),state,voice_id,str(generation)],
                           stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                           env=env,start_new_session=True)
    try:
        child.stdin.write(text.encode('utf-8'));child.stdin.close()
    except (OSError,BrokenPipeError) as exc:
        return {'error':'Voice worker input failed: '+str(exc)}
    return {'queued':True,'pid':child.pid,'voice_id':voice_id,'generation':generation}


def play(text,state,voice_id,generation=0):
    def current():
        return mod_switches.is_on('voice',state) and mod_switches.setting('voice-generation',state)==generation
    with speech_lock.acquire():
        if not current():
            return record(state,voice_id,'stopped',characters=len(text))
        record(state,voice_id,'playing',characters=len(text))
        try:
            subprocess.run([SAY,'-s'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5)
        except (OSError,subprocess.SubprocessError):pass
        # /voice off is served by the open chat while this worker owns playback.
        if not current():
            return record(state,voice_id,'stopped',characters=len(text))
        try:
            child=subprocess.Popen([SAY,text],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            while True:
                try:
                    _,error=child.communicate(timeout=.1)
                    break
                except subprocess.TimeoutExpired:
                    if not current():
                        try:subprocess.run([SAY,'-s'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5)
                        except (OSError,subprocess.SubprocessError):pass
                        if child.poll() is None:child.terminate()
            code=child.returncode
        except OSError as exc:
            return record(state,voice_id,'error',characters=len(text),error=str(exc))
        status='played' if code==0 else 'stopped' if not current() else 'error'
        return record(state,voice_id,status,characters=len(text),exit_code=code,error=error.strip())


if __name__=='__main__':
    if len(sys.argv)!=4:raise SystemExit('usage: voice_playback.py STATE VOICE_ID GENERATION')
    answer=sys.stdin.read()
    result=play(answer,sys.argv[1],sys.argv[2],int(sys.argv[3]))
    raise SystemExit(1 if result['status']=='error' else 0)
