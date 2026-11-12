"""The API usage alarm: a phone timer saves exact local meters every 15 minutes."""
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import mod_switches
import usage_meter

ROOT=Path(__file__).resolve().parent


def tick(state, *, notify=False, now=None):
    state=Path(state)
    if not mod_switches.is_on('usage-alarm',state):
        return {'status':'off'}
    now=now or datetime.now(usage_meter.local_zone())
    starts=usage_meter.window_starts(now)
    data={'status':'saved','at':now.isoformat(),'windows':{key:value.isoformat() for key,value in starts.items()},
          'calls':usage_meter.from_log(state/'usage.jsonl',starts,now),
          'turns':usage_meter.from_history(state/'history.db',starts,now)}
    folder=state/'usage-alarm';folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    temporary=folder/'.latest.tmp'
    temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n');temporary.replace(folder/'latest.json')
    if notify:
        lines=[]
        for engine,lane,_ in usage_meter.LANES:
            day=data['calls'][engine]['today']
            lines.append(f'{lane}: {day["calls"]:,} calls, {day["input"]+day["output"]:,} tokens today')
        done=subprocess.run(['/data/data/com.termux/files/usr/bin/termux-notification','--id','lane-usage',
                             '--title','Lane usage','--content','\n'.join(lines),'--priority','low'],
                            capture_output=True,text=True,timeout=30)
        data['notification_exit']=done.returncode
        if done.returncode: data.update(status='error',error=done.stderr.strip())
    return data


def main(argv=None):
    args=list(sys.argv[1:] if argv is None else argv)
    state=Path(os.environ.get('HARNESS_STATE_DIR') or ROOT/'state')
    result=tick(state,notify='test' in args)
    print(json.dumps(result,ensure_ascii=False))
    return 1 if result['status']=='error' else 0


if __name__=='__main__':raise SystemExit(main())
