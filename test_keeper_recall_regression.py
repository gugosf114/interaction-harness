"""Real shell keeper startup races, isolated by exact HARNESS_STATE_DIR."""
import fcntl
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import unittest

ROOT=Path(__file__).resolve().parent
KEEPER=ROOT/'agentd/keeper.sh'


def read(path):
    try:return path.read_bytes()
    except OSError:return b''


class KeeperLockRegression(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.state=Path(self.tmp.name)/'state';self.home=self.state/'agentd';self.home.mkdir(parents=True)
        self.fake=Path(self.tmp.name)/'fakepy'
        self.fake.write_text('#!/bin/sh\necho $$ > "$HARNESS_STATE_DIR/agentd/daemon.pid"\nexec python3 -c "import time; time.sleep(300)" agentd _daemon\n')
        self.fake.chmod(0o755)
        self.env={**os.environ,'HARNESS_STATE_DIR':str(self.state),'AGD_PYTHON':str(self.fake),'AGD_SEC':'1'}
        self.processes=[]

    def tearDown(self):
        subprocess.run(['sh',str(KEEPER),'stop'],env=self.env,timeout=30,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        for process in self.processes:
            if process.poll() is None:process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait()
        owned=[]
        marker=('HARNESS_STATE_DIR='+str(self.state)).encode()+b'\0'
        for proc in Path('/proc').iterdir():
            if proc.name.isdigit() and marker in read(proc/'environ'):
                args=read(proc/'cmdline').split(b'\0')
                if b'agentd' in args and b'_daemon' in args or b'sleep' in args and b'300' in args:
                    owned.append(int(proc.name))
        for pid in [*self.watchers(),*owned]:
            try:os.kill(pid,signal.SIGKILL)
            except ProcessLookupError:pass

    def watchers(self):
        from keeper_test_processes import watchers
        return watchers(self.state)

    def start(self):
        p=subprocess.Popen(['sh',str(KEEPER),'watch'],env=self.env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        self.processes.append(p);return p

    def until(self,predicate):
        end=time.monotonic()+15
        while time.monotonic()<end:
            if predicate():return
            time.sleep(0.05)
        self.fail('Keeper condition did not become true.')

    def pid(self,name):
        try:return int((self.home/name).read_text())
        except (OSError,ValueError):return None

    def test_kernel_lock_serializes_concurrent_starts_and_keeps_inode(self):
        lock=self.home/'keeper.flock'
        with lock.open('a') as held:
            inode=lock.stat().st_ino
            fcntl.flock(held,fcntl.LOCK_EX)
            starts=[self.start() for _ in range(8)]
            for p in starts:
                try:p.wait(timeout=4)
                except subprocess.TimeoutExpired:self.fail('A watcher ignored the held kernel lock.')
                self.assertEqual(p.returncode,0)
            self.assertIsNone(self.pid('daemon.pid'))
            fcntl.flock(held,fcntl.LOCK_UN)
        starts=[self.start() for _ in range(12)]
        self.until(lambda:self.pid('daemon.pid') is not None)
        self.until(lambda:len([p for p in starts if p.poll() is None])==1)
        self.assertEqual(len(self.watchers()),1)
        self.assertEqual(lock.stat().st_ino,inode)

    def test_daemon_does_not_hold_watch_lock_after_watcher_dies(self):
        first=self.start();self.until(lambda:self.pid('daemon.pid') is not None)
        daemon=self.pid('daemon.pid');lock=self.home/'keeper.flock';inode=lock.stat().st_ino
        self.assertNotEqual(os.readlink(f'/proc/{daemon}/fd/9') if Path(f'/proc/{daemon}/fd/9').exists() else None,str(lock))
        first.kill();first.wait()
        second=self.start();self.until(lambda:self.pid('keeper.lock/pid')==second.pid)
        self.assertEqual(self.pid('daemon.pid'),daemon)
        self.assertEqual(lock.stat().st_ino,inode)
        self.assertEqual(len(self.watchers()),1)

    def test_running_legacy_keeper_is_preserved(self):
        legacy=subprocess.Popen(['sh','-c','sleep 300; :','agentd/keeper.sh','watch'],env=self.env)
        self.processes.append(legacy)
        (self.home/'keeper.lock').mkdir();pidfile=self.home/'keeper.lock/pid';pidfile.write_text(str(legacy.pid)+'\n')
        new=self.start();self.assertEqual(new.wait(timeout=5),0)
        self.assertIsNone(legacy.poll());self.assertEqual(pidfile.read_text(),str(legacy.pid)+'\n')
        self.assertIsNone(self.pid('daemon.pid'))


class KeeperProcessCounting(unittest.TestCase):
    def test_helpers_are_excluded_but_two_independent_watchers_remain_two(self):
        from keeper_test_processes import independent_pids
        self.assertEqual(independent_pids([{'pid':1,'ppid':0},{'pid':2,'ppid':1},{'pid':3,'ppid':2}]),[1])
        self.assertEqual(independent_pids([{'pid':1,'ppid':0},{'pid':2,'ppid':0}]),[1,2])


if __name__=='__main__':unittest.main()
