"""Copy a SQLite snapshot into an empty PostgreSQL application schema.

The source is opened read-only. The destination import is one transaction.
Do not run while source writers are active; stop API/worker/scheduler first.
"""
import argparse
import sqlite3
from pathlib import Path

from psycopg import sql

from orchestrator_core.storage.postgres import connect, migrate


def transfer(source, destination):
    source_path = Path(source).resolve(strict=True)
    src = sqlite3.connect(source_path.as_uri() + '?mode=ro', uri=True)
    dst = connect(destination, pooled=False)
    try:
        if src.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Source database failed its integrity check')
        migrate(dst)
        from orchestrator_core.storage.db import SCHEMA_SQL
        import re
        tables = re.findall(r'CREATE TABLE IF NOT EXISTS (\w+)', SCHEMA_SQL)
        with dst:
            dst.execute('SELECT pg_advisory_xact_lock(74201902)')
            for table in tables:
                count = dst.raw.execute(sql.SQL('SELECT COUNT(*) FROM {}').format(sql.Identifier(table))).fetchone()[0]
                if count and table != 'system_flags':
                    raise ValueError('Destination must be empty; existing rows were preserved')
            dst.execute('DELETE FROM system_flags')
            for table in tables:
                if not src.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                    continue
                cursor = src.execute(f'SELECT * FROM "{table}"')
                columns = [column[0] for column in cursor.description]
                statement = sql.SQL('INSERT INTO {} ({}) VALUES ({})').format(
                    sql.Identifier(table), sql.SQL(',').join(map(sql.Identifier, columns)),
                    sql.SQL(',').join(sql.Placeholder() for _ in columns))
                for row in cursor:
                    dst.raw.execute(statement, row)
            dst.execute("SELECT setval(pg_get_serial_sequence('pipeline_steps','id'), COALESCE(MAX(id),1), MAX(id) IS NOT NULL) FROM pipeline_steps")
    finally:
        src.close()
        dst.close()


def main():
    import os
    from dotenv import load_dotenv
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source')
    args = parser.parse_args()
    transfer(args.source, os.environ['MIGRATION_DATABASE_URL'])
    print('SQLite source preserved; PostgreSQL import committed.')


if __name__ == '__main__':
    main()
