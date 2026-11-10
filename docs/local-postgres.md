# Local PostgreSQL

PostgreSQL 16 runs through Docker Compose and listens only on `127.0.0.1:5432`.
Its data survives container replacement in the `postgres_data` named volume.
Fresh database volumes require SCRAM-SHA-256 authentication for local and host
connections, and the base image is pinned by digest.

## First start

```powershell
python scripts/setup_local_postgres.py
docker compose up -d postgres
docker compose ps postgres
```

The setup script generates three different local credentials in the ignored
`.env` file. It does not replace existing values or print secrets.

Verify readiness and inspect roles without copying a password into the shell:

```powershell
docker compose exec postgres pg_isready -U orchestrator_bootstrap -d orchestrator
docker compose exec postgres psql -U orchestrator_bootstrap -d orchestrator -c "\du"
```

Stop the service without deleting its data:

```powershell
docker compose down
```

Do not run `docker compose down -v` unless permanent deletion of the local
database is intended.

## Security model

## Application migration

The application now selects PostgreSQL when `DATABASE_URL` is set. Production
and staging require it. Run schema migrations separately with
`python -m orchestrator_core.storage.migrate` and `MIGRATION_DATABASE_URL`.
For commands on Windows, use `127.0.0.1` as the URL host; Compose uses `postgres`.
The API role only checks the schema version and never runs DDL.

To retain existing application state, stop its writers and run
`python -m orchestrator_core.storage.import_sqlite database/orchestrator.db`.
The source is read-only and destination inserts commit together. Existing
destination application records cause the import to stop without replacement.
The SQLite source remains the rollback copy. Do not resume writes to both stores.
Legacy `tracker.db` is a separate experimental database and is not imported.

Connections are capped at 12 per process, with five-second acquisition/connect
timeouts, five-second lock waits, and fifteen-second statement timeouts.
Database errors propagate rather than falling back to SQLite.

- `orchestrator_bootstrap` initializes the container and is not given to the app.
- `orchestrator_migrator` owns the application schema and performs migrations.
- `orchestrator_app` receives data access on objects created by the migrator but
  cannot create roles, databases, or schemas.
- SQLite remains available only for development/tests until the Phase 2.1
  application migration is complete.
