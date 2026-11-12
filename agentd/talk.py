"""`talk`: a spoken conversation with a lane.

Each turn: record from the phone's microphone (termux-microphone-record), turn the speech into text with OpenAI's
transcription endpoint (POST /v1/audio/transcriptions, model gpt-transcribe), hand the text to the lane as a job in one
session that lasts the whole conversation, print the answer, and speak it with George's voice tool (deb say).
The lane's reply goes through every harness gate, like any other turn.

Why this road (checked Nov 11, 2026):
- Anthropic's Claude API lists no audio input, speech-to-text, speech output or realtime voice feature.
- OpenAI's Realtime API (gpt-realtime-2.1, WebRTC or WebSocket) talks speech to speech with its own model. Its answer
  would skip the harness: no four-field reply, no gates, no lane, no history.db row. So it does not fit a lane.
- OpenAI's transcription endpoint takes the recorded file in one request and returns the words. That is the most
  direct road that keeps the lane in the middle.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request

from . import config

TRANSCRIBE_URL = 'https://api.openai.com/v1/audio/transcriptions'
TRANSCRIBE_MODEL = 'gpt-transcribe'
MAX_AUDIO_BYTES = 25 * 1024 * 1024  # the endpoint's file cap
STOP_WORDS = re.compile(r'^\W*(stop|goodbye|good bye|bye|exit|quit|end)\W*$', re.IGNORECASE)
MEDIA = {'.m4a': 'audio/mp4', '.mp4': 'audio/mp4', '.mp3': 'audio/mpeg', '.wav': 'audio/wav', '.ogg': 'audio/ogg',
         '.webm': 'audio/webm', '.flac': 'audio/flac', '.mpga': 'audio/mpeg', '.mpeg': 'audio/mpeg'}


class TalkError(Exception):
    pass


def openai_key() -> str:
    value = os.environ.get('OPENAI_API_KEY', '').strip()
    if value:
        return value
    try:
        return (config.ROOT / 'state' / 'api-key').read_text().strip()
    except OSError:
        raise TalkError('No OpenAI key: export OPENAI_API_KEY or save it with export-key.sh.')


def multipart(fields: dict, file_field: str, path: Path):
    boundary = 'agentd' + secrets.token_hex(12)
    parts = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    media = MEDIA.get(path.suffix.lower(), 'application/octet-stream')
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{path.name}"\r\n'
                 f'Content-Type: {media}\r\n\r\n'.encode() + path.read_bytes() + b'\r\n')
    parts.append(f'--{boundary}--\r\n'.encode())
    return b''.join(parts), f'multipart/form-data; boundary={boundary}'


def transcribe(path, key=None, opener=urllib.request.urlopen, model=TRANSCRIBE_MODEL) -> str:
    path = Path(path)
    size = path.stat().st_size
    if size == 0:
        raise TalkError('The recording is empty.')
    if size > MAX_AUDIO_BYTES:
        raise TalkError('The recording is over 25 MB.')
    body, content_type = multipart({'model': model, 'response_format': 'json'}, 'file', path)
    request = urllib.request.Request(TRANSCRIBE_URL, data=body, method='POST',
                                     headers={'Authorization': f'Bearer {key or openai_key()}', 'Content-Type': content_type})
    try:
        with opener(request, timeout=180) as response:
            data = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', 'replace')
        try:
            detail = json.loads(detail).get('error', {}).get('message') or detail
        except (ValueError, AttributeError):
            pass
        raise TalkError(f'Transcription HTTP {exc.code}: {detail[:300]}')
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise TalkError(f'Transcription failed: {exc}')
    return str(data.get('text') or '').strip()


def run(argv, timeout=60, stdin=subprocess.DEVNULL):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, stdin=stdin)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(argv, 127, '', type(exc).__name__)


def record(path: Path, seconds: int, wait_enter=True) -> Path:
    """Record from the phone's microphone until Enter or the time limit. termux-microphone-record writes AAC in .m4a."""
    tool = config.TERMUX_BIN + '/termux-microphone-record'
    run([tool, '-q'], 15)  # a recording left over from an earlier run would block this one
    started = run([tool, '-f', str(path), '-l', str(seconds), '-e', 'aac'], 30)
    if started.returncode != 0 or 'Recording started' not in (started.stdout + started.stderr):
        raise TalkError('The microphone did not start: ' + (started.stdout + started.stderr).strip()[:200])
    print(f'Listening. Speak now; Enter ends the turn ({seconds} s at most).', file=sys.stderr, flush=True)
    deadline = time.time() + seconds
    if wait_enter and sys.stdin.isatty():
        import select
        while time.time() < deadline:
            ready, _, _ = select.select([sys.stdin], [], [], 0.25)
            if ready:
                sys.stdin.readline()
                break
    else:
        time.sleep(seconds)
    run([tool, '-q'], 15)
    for _ in range(20):  # the file is finished a moment after the stop
        if path.exists() and path.stat().st_size > 0:
            break
        time.sleep(0.25)
    time.sleep(0.5)
    return path


def ask_lane(paths, lane, session, text, timeout=None):
    """The words go to the lane as a job in the talk session. Returns the finished job."""
    from .cli import keeper
    from .jobs import FINAL, Queue
    queue = Queue(paths)
    try:
        job = queue.add(lane, text, session=session, door='talk')
        keeper('start', paths)
        deadline = time.time() + timeout if timeout else None
        while job['state'] not in FINAL:
            if deadline and time.time() > deadline:
                raise TalkError(f"job {job['id']} is still {job['state']}.")
            time.sleep(0.5)
            job = queue.get(job['id'])
        return job
    except KeyboardInterrupt:
        if 'job' in locals():
            queue.request_stop(job['id'])
        raise
    finally:
        queue.close()


def speak(text):
    if not text:
        return False
    return run([config.TERMUX_BIN + '/proot-distro', 'login', 'debian', '--', 'say', text], 900).returncode == 0


def main(argv=None, paths=None) -> int:
    parser = argparse.ArgumentParser(prog='talk', description='A spoken conversation with a lane.')
    parser.add_argument('--lane', help='george, g1, or any lane in the ~/.bashrc shortcut block.')
    parser.add_argument('--session', help='Continue this harness session. Default: a new talk-TIME session.')
    parser.add_argument('--seconds', type=int, default=60, help='Longest recording per turn (default 60, at most 600).')
    parser.add_argument('--clip', action='append', default=[], metavar='FILE',
                        help='Use this recorded file instead of the microphone; repeat for more turns.')
    parser.add_argument('--no-speak', action='store_true', help='Print the answer only.')
    args = parser.parse_args(argv)
    if not 1 <= args.seconds <= 600:
        parser.error('--seconds must be between 1 and 600.')
    paths = paths or config.Paths()
    settings = config.load_settings(paths)
    table = config.lanes(settings)
    lane = args.lane or config.default_lane(settings, table)
    if lane not in table:
        print(f'No lane named {lane}. Lanes: {", ".join(sorted(table))}.', file=sys.stderr)
        return 2
    session = args.session or 'talk-' + time.strftime('%Y%m%d-%H%M%S')
    folder = paths.home / 'talk' / session
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    print(f'talk: lane {lane}, session {session}. Say "stop" to end.', file=sys.stderr)
    clips = [Path(clip).expanduser() for clip in args.clip]
    turn, code = 0, 0
    try:
        while True:
            turn += 1
            if clips:
                if turn > len(clips):
                    break
                audio = clips[turn - 1]
            else:
                audio = record(folder / f'turn-{turn}.m4a', args.seconds)
            try:
                words = transcribe(audio)
            except TalkError as exc:
                print(str(exc), file=sys.stderr)
                code = 2
                if clips:
                    break
                continue
            if not words:
                print('(heard nothing)', file=sys.stderr)
                continue
            print(f'You: {words}', flush=True)
            if STOP_WORDS.match(words):
                break
            job = ask_lane(paths, lane, session, words)
            answer = job.get('answer') or job.get('error') or 'No answer.'
            print(f"{lane}: {answer}", flush=True)
            code = 0 if job['state'] == 'done' else (job['exit_code'] or 1)
            if not args.no_speak and not speak(answer):
                print('The answer was saved, but say failed to play it.', file=sys.stderr)
                code = 2
    except KeyboardInterrupt:
        run([config.TERMUX_BIN + '/termux-microphone-record', '-q'], 15)
        return 130
    return code
