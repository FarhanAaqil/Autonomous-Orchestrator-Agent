"""One encrypted backup with bounded retention, for a daily OS scheduler."""
import json
import os
import re
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from orchestrator_core.storage.postgres_backup import backup


ARCHIVE = re.compile(r"toji-([0-9]{8}T[0-9]{6}Z)-[0-9a-f]{32}\.fernet$")


def run(directory, url, key, retention_days=30):
    if not 7 <= retention_days <= 365:
        raise ValueError('Backup retention must be between 7 and 365 days')
    root = Path(directory).resolve()
    root.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    name = 'toji-' + now.strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex + '.fernet'
    result = backup(url, root / name, key)
    # Prune only this scheduler's archives, after a successful new backup.
    # Never traverse directories or follow symlinks.
    removed = 0
    for candidate in root.iterdir():
        match = ARCHIVE.fullmatch(candidate.name)
        if not match or candidate.is_symlink() or not candidate.is_file():
            continue
        try:
            created = datetime.strptime(match[1], '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if created < now - timedelta(days=retention_days):
            if candidate.resolve().parent != root:
                raise ValueError('Backup path escaped the configured directory')
            candidate.unlink()
            removed += 1
    status = {'completed_at': now.isoformat(), 'bytes': result['bytes'], 'backup_seconds': result['backup_seconds'], 'retention_days': retention_days, 'removed': removed}
    marker = root / ('status-' + uuid.uuid4().hex + '.tmp')
    marker.write_text(json.dumps(status), encoding='utf-8')
    marker.replace(root / 'last-success.json')
    return status


def main():
    try:
        result = run(os.environ['BACKUP_DIRECTORY'], os.environ['MIGRATION_DATABASE_URL'], os.environ['BACKUP_ENCRYPTION_KEY'], int(os.getenv('BACKUP_RETENTION_DAYS', '30')))
    except Exception as exc:
        print(json.dumps({'event': 'backup_failed', 'error_class': type(exc).__name__}))
        return 1
    print(json.dumps({'event': 'backup_completed', **result}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
