"""Ordered schema extensions shared by PostgreSQL and development SQLite."""

IDENTITY_SQL = """
CREATE TABLE IF NOT EXISTS users (
 id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
 role TEXT NOT NULL CHECK(role IN ('administrator','operator','viewer')),
 active INTEGER NOT NULL DEFAULT 1, version INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
 user_version INTEGER NOT NULL, expires_at TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS login_limits (
 key TEXT PRIMARY KEY, attempts INTEGER NOT NULL, reset_at TEXT NOT NULL
);
"""


def migrate_extensions(conn):
    with conn:
        conn.execute('CREATE TABLE IF NOT EXISTS application_migrations (version INTEGER PRIMARY KEY)')
        if getattr(conn, 'dialect', None) == 'postgresql':
            conn.execute('SELECT pg_advisory_xact_lock(74201902)')
        if not conn.execute('SELECT 1 FROM application_migrations WHERE version=2').fetchone():
            for statement in IDENTITY_SQL.split(';'):
                if statement.strip():
                    conn.execute(statement)
            conn.execute('INSERT INTO application_migrations VALUES (2)')
        if not conn.execute('SELECT 1 FROM application_migrations WHERE version=3').fetchone():
            conn.execute('ALTER TABLE jobs ADD COLUMN lease_generation INTEGER NOT NULL DEFAULT 0')
            conn.execute('ALTER TABLE jobs ADD COLUMN lease_expires_at TEXT')
            conn.execute('INSERT INTO application_migrations VALUES (3)')
        if not conn.execute('SELECT 1 FROM application_migrations WHERE version=4').fetchone():
            conn.execute("CREATE TABLE job_dependencies (id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id), kind TEXT NOT NULL CHECK(kind IN ('approval','child')), target_id TEXT NOT NULL, resolved INTEGER NOT NULL DEFAULT 0, outcome_json TEXT, UNIQUE(job_id,kind,target_id))")
            conn.execute('INSERT INTO application_migrations VALUES (4)')
        if not conn.execute('SELECT 1 FROM application_migrations WHERE version=5').fetchone():
            conn.execute("CREATE TABLE provider_usage (id TEXT PRIMARY KEY, job_id TEXT, used_at TEXT NOT NULL, reserved_tokens INTEGER NOT NULL, reserved_cost REAL NOT NULL, tokens_in INTEGER, tokens_out INTEGER, cost_usd REAL, state TEXT NOT NULL)")
            conn.execute('INSERT INTO application_migrations VALUES (5)')
        if not conn.execute('SELECT 1 FROM application_migrations WHERE version=6').fetchone():
            conn.execute("ALTER TABLE schedules ADD COLUMN timezone TEXT NOT NULL DEFAULT 'UTC'")
            conn.execute('CREATE TABLE schedule_occurrences (schedule_id TEXT NOT NULL, due_at TEXT NOT NULL, job_id TEXT NOT NULL REFERENCES jobs(id), PRIMARY KEY(schedule_id,due_at))')
            conn.execute('INSERT INTO application_migrations VALUES (6)')
        if not conn.execute('SELECT 1 FROM application_migrations WHERE version=7').fetchone():
            conn.execute('CREATE TABLE service_heartbeats (role TEXT PRIMARY KEY, beat_at TEXT NOT NULL)')
            conn.execute("UPDATE schedules SET is_active=0 WHERE id IN ('daily_briefing','stale_approval_cleanup')")
            conn.execute('INSERT INTO application_migrations VALUES (7)')
        if not conn.execute('SELECT 1 FROM application_migrations WHERE version=8').fetchone():
            from orchestrator_core.storage.event_schema import install
            install(conn)
            conn.execute('INSERT INTO application_migrations VALUES (8)')
        if not conn.execute('SELECT 1 FROM application_migrations WHERE version=9').fetchone():
            conn.execute('ALTER TABLE memory_items ADD COLUMN vector_synced_at TEXT')
            conn.execute('INSERT INTO application_migrations VALUES (9)')
        if not conn.execute('SELECT 1 FROM application_migrations WHERE version=10').fetchone():
            conn.execute("ALTER TABLE jobs ADD COLUMN work_kind TEXT NOT NULL DEFAULT 'agent'")
            conn.execute("ALTER TABLE jobs ADD COLUMN work_payload_json TEXT NOT NULL DEFAULT '{}'")
            conn.execute('INSERT INTO application_migrations VALUES (10)')
