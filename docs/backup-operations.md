# Scheduled backups and recovery

The opt-in Linux systemd units in `deploy/systemd` run an encrypted PostgreSQL backup every night at 02:15 UTC, with up to five minutes of jitter and catch-up after downtime. They are deployment templates; they have not been installed on a production server.

Prepare a dedicated `toji-backup` OS account, a readable checkout and Python environment at `/opt/toji`, and PostgreSQL client tools matching the database major version (currently 16). Create `/var/lib/toji-backups` owned by that account with mode 0700. The backup account must be able to read all tenant data through a dedicated database backup/migration role, never the restricted application role. Do not grant those credentials to the API process.

Create `/etc/toji/backup.env` readable only by root. Set `BACKUP_DIRECTORY=/var/lib/toji-backups`, `BACKUP_RETENTION_DAYS=30`, `MIGRATION_DATABASE_URL`, and `BACKUP_ENCRYPTION_KEY`. Supply real secrets privately. Store the encryption key separately from archives and preserve older keys until their archives expire. The service uses umask 0077.

Copy the two unit files to `/etc/systemd/system`, run `systemctl daemon-reload`, then run `systemctl start toji-backup.service`. Verify the encrypted archive and `last-success.json`, restore it into a new empty disposable database with the documented restore command, and only then enable `systemctl enable --now toji-backup.timer`.

Retention pruning occurs only after a successful new backup and only touches matching scheduler-created archive names in the configured directory. It does not follow symlinks. Manual archives remain untouched. Failed backups preserve the previous success marker. Copy encrypted archives off-host using the operator's approved storage configuration; a backup on the same disk is not disaster recovery.

Monitor `systemctl is-failed toji-backup.service` and alert if `last-success.json.completed_at` is over 26 hours old. Logs contain completion measurements or exception classes, not URLs, passwords, or provider errors. External uptime monitoring should check the public `/ready` endpoint from outside the VM and alert on repeated failures. Configure the real monitoring destination before launch; none is silently provisioned by this repository.

Restore requires a new empty database. Restored sessions and account recovery tokens are revoked, and memory vectors are marked for rebuilding. Keep the restored instance private until pending account deletions have been reapplied, credentials checked, and readiness/tenant isolation verified. Account deletion does not rewrite existing encrypted archives; the documented retention policy applies. Measure recovery duration and data loss against the chosen recovery objectives on the actual deployment.
