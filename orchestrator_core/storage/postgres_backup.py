"""Authenticated encrypted pg_dump archives; restore only into an empty database."""
import os
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit, unquote

from cryptography.fernet import Fernet


def _run(tool, url, args, data=None):
    parsed = urlsplit(url.replace('postgresql+psycopg://', 'postgresql://', 1))
    env = dict(os.environ, PGPASSWORD=unquote(parsed.password or ''))
    container = os.environ.get('PG_TOOLS_CONTAINER')
    prefix = ['docker', 'exec', '-i', '-e', 'PGPASSWORD', container] if container else []
    port = '5432' if container else str(parsed.port or 5432)
    host = '127.0.0.1' if container else parsed.hostname
    command = prefix + [tool, '-h', host, '-p', port, '-U', unquote(parsed.username), '-d', parsed.path.lstrip('/')] + args
    result = subprocess.run(command, input=data, capture_output=True, env=env, timeout=180)
    if result.returncode:
        raise RuntimeError(f'{tool} failed; destination transaction was not committed')
    return result.stdout


def backup(url, destination, key):
    started = time.monotonic()
    cipher = Fernet(key.encode() if isinstance(key, str) else key)
    dump = _run('pg_dump', url, ['--format=custom', '--no-owner', '--no-acl'])
    if not dump.startswith(b'PGDMP'):
        raise ValueError('PostgreSQL did not produce a custom-format archive')
    encrypted = cipher.encrypt(dump)
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('xb') as output:
        output.write(encrypted)
    return {'path': str(target), 'backup_seconds': time.monotonic()-started, 'bytes': len(encrypted), 'vectors': 'rebuild from reviewed memory rows'}


def restore(archive, destination_url, key):
    from orchestrator_core.storage.postgres import connect, verify_schema
    started = time.monotonic()
    # Authenticate the entire archive before accessing the destination.
    cipher = Fernet(key.encode() if isinstance(key, str) else key)
    dump = cipher.decrypt(Path(archive).read_bytes())
    if not dump.startswith(b'PGDMP'):
        raise ValueError('Invalid PostgreSQL archive')
    db = connect(destination_url, pooled=False)
    try:
        if db.execute("SELECT 1 FROM information_schema.tables WHERE table_schema='public' LIMIT 1").fetchone():
            raise ValueError('Restore requires an empty destination database; existing data was preserved')
    finally:
        db.close()
    _run('pg_restore', destination_url, ['--single-transaction', '--exit-on-error', '--no-owner', '--no-acl'], dump)
    db = connect(destination_url, pooled=False)
    try:
        verify_schema(db)
        with db:
            db.execute('UPDATE memory_items SET vector_synced_at=NULL')
            # Restored browser sessions must not resurrect previously revoked access.
            db.execute('DELETE FROM sessions')
    finally:
        db.close()
    return {'restore_seconds': time.monotonic()-started, 'vectors': 'rebuild pending', 'sessions': 'revoked'}


def main():
    import argparse
    from dotenv import load_dotenv
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['backup','restore'])
    parser.add_argument('archive')
    args = parser.parse_args()
    key = os.environ['BACKUP_ENCRYPTION_KEY']
    if args.operation == 'backup':
        result = backup(os.environ['MIGRATION_DATABASE_URL'], args.archive, key)
    else:
        result = restore(args.archive, os.environ['RESTORE_DATABASE_URL'], key)
    print(result)


if __name__ == '__main__':
    main()
