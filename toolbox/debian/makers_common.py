#!/usr/bin/python3
"""Shared by the Debian halves of the maker commands: the pinned library folder, the saved keys, one HTTP helper.

Run it by itself to see which pinned libraries are in place:  python3 makers_common.py
"""
import glob
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[2]
LIVE_STATE = Path('/data/data/com.termux/files/home/interaction-harness/state')
VENV = Path(os.environ.get('HARNESS_MAKERS_VENV', '/root/.local/share/harness-makers/venv'))
INSTALLER = ROOT / 'toolbox/debian/makers-install.sh'
# Exact versions, including the office libraries' dependencies.
PINS = dict(line.split('==', 1) for line in (ROOT / 'toolbox/makers-requirements.lock').read_text().splitlines() if line.strip())

KEY_FILE = {'openai': 'api-key', 'gemini': 'gemini-api-key'}
KEY_ENV = {'openai': 'OPENAI_API_KEY', 'gemini': 'GEMINI_API_KEY'}
GEMINI_SECRET = ['gcloud', 'secrets', 'versions', 'access', 'latest', '--secret', 'gemini-api-key',
                 '--project', 'bakers-agent', '--account=gugosf@gmail.com']


class MakerError(Exception):
    """One short line for stderr."""


def add_libraries():
    """Put the pinned libraries on the import path. They sit in one private folder, not in Debian's own Python."""
    for folder in sorted(glob.glob(str(VENV / 'lib' / 'python3*' / 'site-packages'))):
        if folder not in sys.path:
            sys.path.insert(0, folder)  # in front, so a pinned version wins over Debian's own copy


def need(module):
    """Import one pinned library, or stop with the one command that installs it."""
    add_libraries()
    try:
        return __import__(module)
    except ImportError as exc:
        raise MakerError(f'The Python module {module} is missing on the Debian side. Install it once:  deb bash {INSTALLER}') from exc


def load_key(engine, run=subprocess.run):
    """The provider key: the environment, then this copy's state folder, then the live folder's. Never printed."""
    value = os.environ.get(KEY_ENV[engine], '').strip()
    for folder in (ROOT / 'state', LIVE_STATE):
        if value:
            break
        try:
            value = (folder / KEY_FILE[engine]).read_text().strip()
        except OSError:
            continue
    if not value and engine == 'gemini':
        # The Gemini key lives in Google Secret Manager (card cloud). It is read into memory for this one run.
        try:
            done = run(GEMINI_SECRET, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise MakerError('gemini: gcloud could not read the secret gemini-api-key (' + exc.__class__.__name__ + ').') from exc
        if done.returncode != 0:
            lines = (done.stderr or '').strip().splitlines()
            raise MakerError('gemini: gcloud could not read the secret gemini-api-key: ' + (lines[-1] if lines else 'no output') + '.')
        value = done.stdout.strip()
    if not value or '\n' in value:
        raise MakerError(f'{engine}: no key found. Looked at {KEY_ENV[engine]} and state/{KEY_FILE[engine]}.')
    return value


def http(url, *, headers=None, body=None, data=None, method=None, timeout=900, opener=urllib.request.urlopen):
    """One HTTP call. Returns (status, bytes). An HTTP error returns its status and body; it does not raise."""
    headers = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    request = urllib.request.Request(url, data=data, headers=headers, method=method or ('POST' if data is not None else 'GET'))
    try:
        with opener(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except (urllib.error.URLError, OSError) as exc:
        raise MakerError(f'no answer from {url.split("?")[0]} ({getattr(exc, "reason", exc)}).') from exc


def provider_error(status, raw):
    """The provider's own words: 'HTTP 400: message'. An empty body is said plainly."""
    text = raw.decode('utf-8', errors='replace').strip()
    if not text:
        return f'HTTP {status}, empty body'
    try:
        error = json.loads(text).get('error')
        if isinstance(error, dict) and error.get('message'):
            text = str(error['message'])
        elif isinstance(error, str):
            text = error
    except (ValueError, AttributeError):
        pass
    return f'HTTP {status}: {text[:1500]}'


def multipart(fields, files):
    """multipart/form-data for (name, value) fields and (name, filename, content type, bytes) files."""
    edge = 'harness' + uuid.uuid4().hex[:24]
    parts = []
    for name, value in fields:
        parts.append(f'--{edge}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'.encode() + str(value).encode('utf-8') + b'\r\n')
    for name, filename, kind, content in files:
        parts.append(f'--{edge}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                     f'Content-Type: {kind}\r\n\r\n'.encode() + content + b'\r\n')
    return b''.join(parts) + f'--{edge}--\r\n'.encode(), 'multipart/form-data; boundary=' + edge


def image_kind(data):
    """The picture type by its first bytes, or None."""
    if data.startswith(b'\x89PNG\r\n\x1a\n'): return 'image/png'
    if data.startswith(b'\xff\xd8\xff'): return 'image/jpeg'
    if data.startswith(b'RIFF') and data[8:12] == b'WEBP': return 'image/webp'
    if data[:6] in (b'GIF87a', b'GIF89a'): return 'image/gif'
    return None


def out_path(value, endings):
    """The output file as a full path. Its folder must exist; its name must end in one of the endings."""
    path = Path(os.path.abspath(os.path.expanduser(value)))
    if not path.name.lower().endswith(tuple(endings)):
        raise MakerError('OUT must end in ' + ' or '.join(endings) + '.')
    if not path.parent.is_dir():
        raise MakerError(f'The folder {path.parent} does not exist.')
    return path


def write_whole(path, data):
    """All or nothing: a failed write leaves no half file under the final name."""
    fd, temp = tempfile.mkstemp(prefix='.maker-', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def read_input(source=None):
    """The text to turn into a file: a named file, or stdin."""
    if source:
        try:
            return Path(os.path.expanduser(source)).read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError) as exc:
            raise MakerError(f'Cannot read {source}: {exc.__class__.__name__}.') from exc
    if sys.stdin is None or sys.stdin.isatty():
        raise MakerError('No input. Pipe the text in, or name an input file.')
    return sys.stdin.read()


def main():
    add_libraries()
    from importlib import metadata
    status = 0
    for name, pin in PINS.items():
        try:
            distribution = metadata.distribution(name)
            found = distribution.version if str(distribution.locate_file('')).startswith(str(VENV)) else None
        except metadata.PackageNotFoundError:
            found = None
        mark = 'ok' if found == pin else 'MISSING' if found is None else 'DIFFERENT'
        if mark != 'ok':
            status = 1
        print(f'{name:18} pinned {pin:8} found {found or "-":8} {mark}')
    print('library folder: ' + str(VENV))
    return status


if __name__ == '__main__':
    raise SystemExit(main())
