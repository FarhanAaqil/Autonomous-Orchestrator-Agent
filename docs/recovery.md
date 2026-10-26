# Recovery

PostgreSQL backups use pg_dump custom format encrypted and authenticated with
Fernet. `BACKUP_ENCRYPTION_KEY` is generated into the ignored local .env. Keep a
separate protected copy of that key; losing it makes the archives unreadable.

On Windows use `PG_TOOLS_CONTAINER=toji_postgres` so dump/restore utilities run
inside the database container. The Python connection URLs for host commands
must use 127.0.0.1. Set MIGRATION_DATABASE_URL for backup and a separate
RESTORE_DATABASE_URL for restore. Never print or pass passwords as CLI arguments.

Commands:

```
python -m orchestrator_core.storage.postgres_backup backup backups/release.dump.enc
python -m orchestrator_core.storage.postgres_backup restore backups/release.dump.enc
```

The restore destination must already exist and have no application tables.
Create it with an administrator and grant the migration role its schema rights.
Restore never drops or replaces the live database. Stop API/worker/scheduler,
verify the restored schema and known records, then change their DATABASE_URL
to the restored database and restart. Preserve the previous database for rollback.
Browser sessions are revoked after restore. Vector indexes are derived from
memory rows and are queued for rebuilding; reviewed text remains available while
the vector backend is unavailable.

The small disposable Phase 2 drill measured 0.33s backup and 0.41s restore. These
are fixture measurements, not production objectives. Recovery point equals the
last successfully authenticated snapshot; schedule frequency determines loss.

Development SQLite restores preserve a rollback database. Vector archives are
validated and extracted to staging before a directory swap; the old directory is
retained with a `.rollback-...` suffix. Corrupt archives leave live data unchanged.
