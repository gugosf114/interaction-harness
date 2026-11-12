"""Keep memory snapshots in lane state. The human-maintained source is read-only."""
from pathlib import Path
import fcntl
import hashlib
import json
import subprocess

SOURCE = Path('/root/.claude/projects/-root/memory')


def snapshot(state, source=None):
    source = Path(source or SOURCE).resolve()
    target = (Path(state) / 'memory-versions').resolve()
    if target == source or source in target.parents or target in source.parents:
        raise ValueError('Memory versions must be outside the source notes.')
    if not source.is_dir():
        return {'status': 'missing_source', 'source': str(source)}
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (target / '.snapshot.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        def git(*args):
            return subprocess.check_output(['git', '-C', str(target), '-c', 'user.name=Lane memory versions',
                                           '-c', 'user.email=lanes@localhost', *args], stderr=subprocess.PIPE, text=True).strip()
        if not (target / '.git').is_dir():
            git('init', '-q')
        notes = target / 'notes'
        notes.mkdir(exist_ok=True)
        manifest = {}
        for path in sorted(source.rglob('*')):
            relative = path.relative_to(source)
            if '.git' in relative.parts or path.is_symlink() or not path.is_file():
                continue
            data = path.read_bytes()
            dest = notes / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists() or dest.read_bytes() != data:
                dest.write_bytes(data)
            manifest[str(relative)] = hashlib.sha256(data).hexdigest()
        for path in notes.rglob('*'):
            if path.is_file() and str(path.relative_to(notes)) not in manifest:
                path.unlink()
        (target / 'source.json').write_text(json.dumps({'source': str(source), 'files': manifest}, sort_keys=True)+'\n')
        git('add', '--all', '--', 'notes', 'source.json')
        changed = bool(git('diff', '--cached', '--name-only'))
        if changed:
            git('commit', '-q', '-m', 'Snapshot memory notes')
        return {'status': 'saved' if changed else 'unchanged', 'commit': git('rev-parse', 'HEAD'),
                'source': str(source), 'files': len(manifest)}
