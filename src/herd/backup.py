"""Offline state backup with SQLite snapshots and verified restore to an empty path."""
from __future__ import annotations

import fcntl
import hashlib
import json
import shutil
import sqlite3
from contextlib import ExitStack
from pathlib import Path

from herd.schemas import digest, utcnow
from herd.store import Store


def backup_state(source: Path, destination: Path) -> dict:
    source, destination = source.resolve(), destination.resolve()
    if not source.is_dir() or destination.exists() or source == destination or source in destination.parents:
        raise ValueError('Use an existing state directory and a new destination outside it')
    with ExitStack() as stack:
        for name in ('maintenance.lock', 'scheduler.lock', 'evidence.lock'):
            lock = stack.enter_context((source / name).open('a'))
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('Stop the scheduler and evidence service before backing up') from None
        store = Store(source / 'herd.sqlite3')
        experiments = store.experiments()
        if any(e.get('status') == 'running' for e in experiments):
            raise ValueError('Pause experiments and stop the API/evidence service before backing up')
        for experiment in experiments:
            lock_path = source / 'locks' / (digest(experiment['id']) + '.lock')
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            lock = stack.enter_context(lock_path.open('a'))
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('A worker still holds an experiment lock') from None
        destination.mkdir(mode=0o700)
        for path in source.rglob('*'):
            relative = path.relative_to(source)
            if path.is_symlink():
                raise ValueError('State backup refuses symlinks')
            if any(part.startswith('.env') or part in {'secrets', 'locks', '__pycache__'} for part in relative.parts):
                continue
            if not path.is_file() or path.name.endswith(('-wal', '-shm', '.lock')):
                continue
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if path.suffix in {'.sqlite3', '.sqlite', '.db'}:
                with sqlite3.connect(path) as original, sqlite3.connect(target) as snapshot:
                    original.backup(snapshot)
            else:
                shutil.copyfile(path, target)
        files = {str(p.relative_to(destination)): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in destination.rglob('*') if p.is_file()}
        manifest = {'created_at': utcnow(), 'files': files,
                    'experiments': [e['id'] for e in experiments], 'version': 1}
        (destination / 'backup-manifest.json').write_text(json.dumps(manifest, indent=2))
        return manifest


def restore_state(backup: Path, destination: Path) -> dict:
    backup, destination = backup.resolve(), destination.resolve()
    if destination.exists():
        raise ValueError('Restore requires a new destination; existing state is never overwritten')
    manifest = json.loads((backup / 'backup-manifest.json').read_text())
    if manifest.get('version') != 1 or not isinstance(manifest.get('files'), dict) or 'herd.sqlite3' not in manifest['files']:
        raise ValueError('Invalid or incomplete backup manifest')
    for relative, expected in manifest['files'].items():
        path = backup / relative
        if Path(relative).is_absolute() or '..' in Path(relative).parts or path.is_symlink() or not path.resolve().is_relative_to(backup):
            raise ValueError('Unsafe backup path')
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Backup checksum mismatch')
    import tempfile
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.herd-restore-', dir=destination.parent))
    try:
        for relative in manifest['files']:
            target = temporary / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(backup / relative, target)
        store = Store(temporary / 'herd.sqlite3')
        try:
            if store.health()['database'] != 'ok' or not all(store.verify_events(eid) for eid in manifest['experiments']):
                raise ValueError('Restored state failed integrity verification')
            if sorted(e['id'] for e in store.experiments()) != sorted(manifest['experiments']):
                raise ValueError('Restored experiment manifest mismatch')
        finally:
            store.db.close()
        temporary.rename(destination)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return {'restored': True, 'experiments': manifest['experiments'], 'files': len(manifest['files'])}
