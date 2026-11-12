"""Count independent watch starters in the real-shell keeper tests.

The fixtures start watchers from the test process. A shell pipeline can fork a
child which retains the watcher's argv and environment until exec. That child
is not a second watch loop. Independent starters remain separate candidates.
"""
import os
from pathlib import Path


def independent_pids(rows):
    parents={row['pid']:row['ppid'] for row in rows}
    return sorted(pid for pid,parent in parents.items() if parent not in parents)


def snapshot(state):
    marker=('HARNESS_STATE_DIR='+str(state)).encode()+b'\0'
    rows=[]
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():continue
        try:
            stat=(proc/'stat').read_text()
            fields=stat[stat.rfind(')')+2:].split()
            cmd=(proc/'cmdline').read_bytes()
            if b'keeper.sh\0watch' not in cmd or marker not in (proc/'environ').read_bytes():continue
            row={'pid':int(proc.name),'ppid':int(fields[1]),'state':fields[0],
                 'start_ticks':int(fields[19]),'cmdline':cmd.replace(b'\0',b' ').decode(errors='replace')}
            try:row['fd9']=os.readlink(proc/'fd/9')
            except OSError:row['fd9']=None
            rows.append(row)
        except (OSError,ValueError,IndexError):continue
    return rows


def watchers(state):
    return independent_pids(snapshot(state))
