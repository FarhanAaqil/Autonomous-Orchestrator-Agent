"""PostgreSQL connections preserving the application's explicit transaction contract.

Only parameter markers are translated; values always remain bound parameters.
Approval BEGIN IMMEDIATE uses a transaction advisory lock shared by all callers.
"""
from __future__ import annotations

import re
import threading
from contextlib import contextmanager

import psycopg
from psycopg.pq import TransactionStatus
from psycopg_pool import ConnectionPool


class Row(dict):
    def __getitem__(self, key):
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


def row_factory(cursor):
    names = [column.name for column in cursor.description] if cursor.description else []
    return lambda values: Row(zip(names, values))


def parameters(sql):
    """Translate qmarks outside SQL strings/identifiers, escaping literal percents."""
    parts = re.split(r"('(?:''|[^'])*'|\"(?:\"\"|[^\"])*\")", sql)
    return ''.join(part.replace('%', '%%').replace('?', '%s') if i % 2 == 0
                   else part.replace('%', '%%') for i, part in enumerate(parts))


class Connection:
    dialect = 'postgresql'

    def __init__(self, raw, release=None):
        self.raw = raw
        self.release = release
        self.closed = False
        self._contexts = []

    @property
    def in_transaction(self):
        return self.raw.info.transaction_status != TransactionStatus.IDLE

    def execute(self, sql, params=()):
        if sql.strip().rstrip(';').upper() == 'BEGIN IMMEDIATE':
            self.raw.execute('BEGIN')
            return self.raw.execute('SELECT pg_advisory_xact_lock(74201901)')
        return self.raw.execute(parameters(sql) if params else sql, params or None)

    def executemany(self, sql, params):
        return self.raw.cursor().executemany(parameters(sql), params)

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()

    def __enter__(self):
        tx = self.raw.transaction()
        tx.__enter__()
        self._contexts.append(tx)
        return self

    def __exit__(self, *exc):
        return self._contexts.pop().__exit__(*exc)

    def close(self):
        if not self.closed:
            self.raw.rollback()
            self.closed = True
            if self.release:
                self.release(self.raw)
            else:
                self.raw.close()


_pools = {}
_lock = threading.Lock()


def connect(url, *, pooled=True):
    url = url.replace('postgresql+psycopg://', 'postgresql://', 1)
    kwargs = dict(autocommit=True, row_factory=row_factory, connect_timeout=5,
                  options='-c statement_timeout=15000 -c lock_timeout=5000 -c timezone=UTC')
    if not pooled:
        return Connection(psycopg.connect(url, **kwargs))
    with _lock:
        if url not in _pools:
            _pools[url] = ConnectionPool(url, min_size=0, max_size=12, timeout=5,
                                         max_waiting=24, kwargs=kwargs, open=True)
        pool = _pools[url]
    return Connection(pool.getconn(), pool.putconn)


def close_pools():
    with _lock:
        for pool in _pools.values():
            pool.close()
        _pools.clear()


def migrate(conn):
    """Versioned, transactional migrations; invoked only with a migration role."""
    from orchestrator_core.storage.db import SCHEMA_SQL
    with conn:
        conn.execute('SELECT pg_advisory_xact_lock(74201902)')
        conn.execute('CREATE TABLE IF NOT EXISTS schema_versions (version INTEGER PRIMARY KEY)')
        if conn.execute('SELECT 1 FROM schema_versions WHERE version=1').fetchone():
            from orchestrator_core.storage.extensions import migrate_extensions
            migrate_extensions(conn)
            return
        schema = SCHEMA_SQL.replace('INTEGER PRIMARY KEY AUTOINCREMENT', 'BIGSERIAL PRIMARY KEY')
        # Preserve exact serialized timestamps used by signed consent records.
        schema = re.sub(r'\bTIMESTAMP\b', 'TEXT', schema).replace('BOOLEAN', 'INTEGER')
        schema = schema.replace('DEFAULT CURRENT_TIMESTAMP', "DEFAULT to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US') || '+00:00'")
        # A parenthesized expression is required for PostgreSQL column defaults.
        schema = schema.replace("DEFAULT to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US') || '+00:00'", "DEFAULT (to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US') || '+00:00')")
        for statement in schema.split(';'):
            if statement.strip():
                conn.execute(statement)
        conn.execute("INSERT INTO system_flags (key,value) VALUES ('kill_switch','off'), ('daily_budget_usd','5.00') ON CONFLICT DO NOTHING")
        conn.execute('INSERT INTO schema_versions VALUES (1)')
        from orchestrator_core.storage.extensions import migrate_extensions
        migrate_extensions(conn)


def verify_schema(conn):
    if not conn.execute("SELECT to_regclass('public.schema_versions')").fetchone()[0]:
        raise RuntimeError('PostgreSQL schema is missing; run python -m orchestrator_core.storage.migrate')
    if not conn.execute('SELECT 1 FROM schema_versions WHERE version=1').fetchone():
        raise RuntimeError('PostgreSQL schema version is unsupported')
