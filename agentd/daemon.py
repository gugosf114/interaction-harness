"""The service: start queued jobs, tell George when one ends, run the doors and the web page."""
from __future__ import annotations

import fcntl
import os
import queue as stdqueue
import signal
import subprocess
import sys
import threading
import time

from . import config
from .jobs import LIVE, Queue, first_line
from .phone import Phone

TICK_SECONDS = 0.5
DELIVERY_TRIES = 5
DELIVERY_GAP_SECONDS = 30


class DeliveryError(Exception):
    """The answer could not go back through its door yet. The service tries again."""


def job_title(job) -> str:
    return f"{job['lane']} job {job['id']} {job['state']}"


def job_line(job) -> str:
    """What the notification shows: the first line of the answer, or why there is none."""
    return first_line(job.get('answer')) or first_line(job.get('error')) or 'No answer.'


class Daemon:
    def __init__(self, paths=None, phone=None, doors=None, serve_web=True):
        self.paths = (paths or config.Paths()).make()
        self.queue = Queue(self.paths)
        self.phone = phone or Phone()
        self.settings, self._settings_mtime = {}, None
        self.children = {}
        self.stop = threading.Event()
        self.speech = stdqueue.Queue()
        self.delivery_tries = {}
        self.notification_wait = {}
        self._status_shown = None
        self._lock_file = None
        self.serve_web = serve_web
        self.web = None
        self.doors_conf, self._doors_mtime = {}, None
        self.reload_settings()
        self.doors = self._build_doors() if doors is None else [make(self) for make in doors]

    # --- small tools -------------------------------------------------------------------------------------
    def log(self, message):
        line = time.strftime('[%Y-%m-%d %H:%M:%S] ') + str(message)
        try:
            with open(self.paths.log, 'a', encoding='utf-8') as stream:
                stream.write(line + '\n')
        except OSError:
            pass

    def reload_settings(self):
        try:
            mtime = self.paths.settings.stat().st_mtime
        except OSError:
            mtime = None
        if mtime == self._settings_mtime and self._settings_mtime is not None:
            return
        self._settings_mtime = mtime
        try:
            self.settings = config.load_settings(self.paths)
        except config.ConfigError as exc:
            self.log(str(exc))
            self.settings = {}

    def reload_doors(self):
        try:
            mtime = self.paths.doors.stat().st_mtime
        except OSError:
            mtime = None
        if mtime == self._doors_mtime and mtime is not None:
            return self.doors_conf
        try:
            self.doors_conf = config.load_doors(self.paths)
            self._doors_mtime = self.paths.doors.stat().st_mtime
        except (config.ConfigError, OSError) as exc:
            self.log(str(exc))
        return self.doors_conf

    def door_conf(self, name) -> dict:
        part = self.reload_doors().get(name)
        return part if isinstance(part, dict) else {}

    def web_password(self) -> str:
        return str(self.door_conf('web').get('password') or '')

    def lanes(self):
        return config.lanes(self.settings)

    def add_job(self, task, lane=None, session=None, door='cli', reply_to=None, source_id=None):
        table = self.lanes()
        lane = lane or config.default_lane(self.settings, table)
        if lane not in table:
            raise ValueError(f'No lane named {lane}. Lanes: {", ".join(sorted(table))}.')
        job = self.queue.add(lane, task, session=session, door=door, reply_to=reply_to, source_id=source_id)
        self.log(f"job {job['id']} queued: lane {lane}, door {door}, session {job['session']}")
        return job

    def _build_doors(self):
        from .doors import build
        return build(self)

    # --- jobs --------------------------------------------------------------------------------------------
    def dispatch(self):
        """Start a runner for every queued job. No cap: each job is its own process."""
        while True:
            job = self.queue.claim()
            if job is None:
                return
            folder = self.paths.jobs / str(job['id'])
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            env = dict(os.environ)
            if self.paths.state != config.state_dir():
                env['HARNESS_STATE_DIR'] = str(self.paths.state)
            try:
                with open(folder / 'runner.log', 'ab') as log:
                    child = subprocess.Popen([sys.executable, '-B', str(config.ROOT / 'toolbox' / 'bin' / 'agentd'), '_jobrun', str(job['id'])],
                                             stdin=subprocess.DEVNULL, stdout=log, stderr=log, env=env, start_new_session=True)
            except OSError as exc:
                self.queue.finish(job['id'], 'failed', error=f'The runner could not start ({type(exc).__name__}).')
                continue
            self.queue.set_pid(job['id'], child.pid)
            self.children[job['id']] = child
            self.log(f"job {job['id']} started (runner pid {child.pid})")

    def reap(self):
        for job_id, child in list(self.children.items()):
            if child.poll() is None:
                continue
            del self.children[job_id]
            job = self.queue.get(job_id)
            if job and job['state'] in LIVE:
                self.queue.finish(job_id, 'interrupted', child.returncode, error='The runner ended without a result.')
            job = self.queue.get(job_id)
            self.log(f"job {job_id} ended: {job['state']}, exit {job['exit_code']}")

    def finish_jobs(self):
        """For each job that ended: the notification, the spoken answer, and the answer back through its door."""
        for job in self.queue.to_notify():
            if time.time() < self.notification_wait.get(job['id'], 0):
                continue
            ok = self.phone.notify(f"agentd-job-{job['id']}", job_title(job), job_line(job),
                                   action=f"termux-open-url http://127.0.0.1:{config.port(self.settings)}/?job={job['id']}")
            if not ok:
                self.log(f"job {job['id']}: notification failed: {getattr(self.phone, 'last_error', '')}")
                self.notification_wait[job['id']] = time.time() + DELIVERY_GAP_SECONDS
                continue
            self.queue.mark_notified(job['id'])
            self.notification_wait.pop(job['id'], None)
            self.log(f"job {job['id']}: notification posted")
            if job.get('answer') and job['door'] != 'talk':  # talk speaks its own answers
                self.speech.put(job)
        doors = {door.name: door for door in self.doors}
        now = time.time()
        for job in self.queue.to_deliver():
            door = doors.get(job['door'])
            if door is None or not hasattr(door, 'deliver'):
                self.queue.mark_delivered(job['id'], 'no door reply')
                continue
            tries, wait_until = self.delivery_tries.get(job['id'], (0, 0))
            if now < wait_until:
                continue
            try:
                note = door.deliver(job)
            except DeliveryError as exc:
                tries += 1
                if tries >= DELIVERY_TRIES:
                    self.queue.mark_delivered(job['id'], f'not delivered: {exc}')
                    self.log(f"job {job['id']}: answer not delivered through {job['door']}: {exc}")
                    self.delivery_tries.pop(job['id'], None)
                else:
                    self.delivery_tries[job['id']] = (tries, now + DELIVERY_GAP_SECONDS)
                continue
            except Exception as exc:  # a door bug must not stop the service
                self.queue.mark_delivered(job['id'], f'not delivered: {type(exc).__name__}')
                self.log(f"job {job['id']}: door {job['door']} failed: {type(exc).__name__}: {exc}")
                continue
            self.queue.mark_delivered(job['id'], note or 'delivered')
            self.delivery_tries.pop(job['id'], None)
            self.log(f"job {job['id']}: answer sent back through {job['door']} ({note or 'delivered'})")

    def show_status(self):
        """One pinned notification while jobs run, one line per job. It goes away when none run."""
        live = self.queue.list(states=LIVE)
        shown = tuple((job['id'], job['state']) for job in live)
        if shown == self._status_shown:
            return
        self._status_shown = shown
        if not live:
            self.phone.remove_notification('agentd-status')
            return
        lines = ' | '.join(f"{job['id']} {job['lane']}: {first_line(job['task'])[:60]}" for job in reversed(live))
        self.phone.notify('agentd-status', f"{len(live)} lane job{'s' if len(live) != 1 else ''} running", lines,
                          ongoing=True, priority='low')

    def speaker(self):
        """Speak one answer at a time, so two jobs that end together do not cut each other off."""
        while not self.stop.is_set():
            try:
                job = self.speech.get(timeout=1)
            except stdqueue.Empty:
                continue
            try:
                state = self.phone.voice_state()
                if state in ('full', 'first'):
                    ok = self.phone.say(job['answer'] if state == 'full' else first_line(job['answer']))
                    self.log(f"job {job.get('id')}: answer spoken ({state}): {'ok' if ok else 'say failed'}")
            except Exception as exc:
                self.log(f'speech failed: {type(exc).__name__}: {exc}')

    def door_loop(self, door):
        while not self.stop.is_set():
            try:
                door.poll()
            except Exception as exc:
                self.log(f'door {door.name}: {type(exc).__name__}: {exc}')
            self.stop.wait(getattr(door, 'interval', 5))

    # --- life --------------------------------------------------------------------------------------------
    def take_lock(self) -> bool:
        self._lock_file = open(self.paths.lock, 'a+')
        try:
            fcntl.flock(self._lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._lock_file.close()
            self._lock_file = None
            return False
        self.paths.pid.write_text(str(os.getpid()))
        return True

    def prepare_history(self):
        """A new history.db is put in WAL mode once here, so jobs that start together do not race to set it."""
        import sqlite3
        try:
            db = sqlite3.connect(self.paths.history, timeout=30)
            try:
                db.execute('PRAGMA journal_mode=WAL')
            finally:
                db.close()
            os.chmod(self.paths.history, 0o600)
        except (sqlite3.Error, OSError) as exc:
            self.log(f'history.db: {exc}')

    def step(self):
        self.reload_settings()
        self.dispatch()
        self.reap()
        self._steps = getattr(self, '_steps', 0) + 1
        if self._steps % 20 == 0:
            self.queue.recover()  # a runner that outlived an earlier service and then died
        if self._steps % 10 == 1:
            self.queue.kv_set('doors', {door.name: door.status() for door in self.doors})
        self.finish_jobs()
        self.show_status()

    def run(self) -> int:
        if not self.take_lock():
            return 0  # another instance holds this state folder
        signal.signal(signal.SIGTERM, lambda *_: self.stop.set())
        signal.signal(signal.SIGINT, lambda *_: self.stop.set())
        self.phone.wake_lock()
        self.prepare_history()
        self.reload_doors()
        lost = self.queue.recover()
        self.log(f'service up, pid {os.getpid()}' + (f'; interrupted jobs: {lost}' if lost else ''))
        threads = [threading.Thread(target=self.speaker, daemon=True)]
        threads += [threading.Thread(target=self.door_loop, args=(door,), daemon=True) for door in self.doors]
        if self.serve_web:
            from .web import start_web
            self.web = start_web(self)
        for thread in threads:
            thread.start()
        try:
            while not self.stop.is_set():
                try:
                    self.step()
                except Exception as exc:
                    self.log(f'step failed: {type(exc).__name__}: {exc}')
                self.stop.wait(TICK_SECONDS)
        finally:
            if self.web:
                self.web.stop()
            for door in self.doors:
                close = getattr(door, 'close', None)
                if close:
                    try:
                        close()
                    except Exception:
                        pass
            try:
                self.paths.pid.unlink()
            except OSError:
                pass
            self.log('service down')
        return 0
