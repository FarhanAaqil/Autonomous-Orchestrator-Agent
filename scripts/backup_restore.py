#!/usr/bin/env python3
"""
scripts/backup_restore.py

CLI tool for creating, verifying, and restoring atomic SQLite and ChromaDB backups.

Usage:
  python scripts/backup_restore.py snapshot [--dest DIR]
  python scripts/backup_restore.py backup-db [--source DB] [--dest DEST]
  python scripts/backup_restore.py restore-db --backup BACKUP [--target TARGET]
  python scripts/backup_restore.py backup-chroma [--dest DEST]
  python scripts/backup_restore.py restore-chroma --archive ARCHIVE [--target TARGET]
  python scripts/backup_restore.py verify --file PATH
"""

import argparse
import sys
from pathlib import Path

from orchestrator_core.storage.backup import (
    backup_chroma,
    backup_sqlite,
    compute_file_sha256,
    create_full_system_snapshot,
    restore_chroma,
    restore_sqlite,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Orchestrator Agent Disaster Recovery Tool")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # snapshot
    p_snap = subparsers.add_parser("snapshot", help="Create full system snapshot (SQLite + Chroma)")
    p_snap.add_argument("--dest", help="Destination directory", default=None)

    # backup-db
    p_bdb = subparsers.add_parser("backup-db", help="Backup SQLite database")
    p_bdb.add_argument("--source", help="Source SQLite DB path", default=None)
    p_bdb.add_argument("--dest", help="Destination DB backup path", default=None)

    # restore-db
    p_rdb = subparsers.add_parser("restore-db", help="Restore SQLite database")
    p_rdb.add_argument("--backup", required=True, help="Backup file path to restore from")
    p_rdb.add_argument("--target", help="Target DB path", default=None)

    # backup-chroma
    p_bchr = subparsers.add_parser("backup-chroma", help="Backup ChromaDB directory to tar.gz")
    p_bchr.add_argument("--source", help="Chroma directory", default=None)
    p_bchr.add_argument("--dest", help="Archive destination path", default=None)

    # restore-chroma
    p_rchr = subparsers.add_parser("restore-chroma", help="Restore ChromaDB from tar.gz")
    p_rchr.add_argument("--archive", required=True, help="Archive path")
    p_rchr.add_argument("--target", help="Target Chroma directory", default=None)

    # verify
    p_v = subparsers.add_parser("verify", help="Verify integrity and compute SHA-256")
    p_v.add_argument("--file", required=True, help="File path to verify")

    args = parser.parse_args()

    try:
        if args.command == "snapshot":
            res = create_full_system_snapshot(output_dir=args.dest)
            print(f"[OK] Full system snapshot created at: {res['snapshot_dir']}")
            print(f"     SQLite SHA256: {res['manifest']['sqlite']['sha256']}")
            print(f"     Chroma SHA256: {res['manifest']['chroma']['sha256']}")
            return 0

        elif args.command == "backup-db":
            path = backup_sqlite(source_path=args.source, dest_path=args.dest)
            sha = compute_file_sha256(path)
            print(f"[OK] Database backed up to: {path}")
            print(f"     SHA-256: {sha}")
            return 0

        elif args.command == "restore-db":
            path = restore_sqlite(backup_path=args.backup, target_path=args.target)
            print(f"[OK] Database restored to: {path}")
            return 0

        elif args.command == "backup-chroma":
            path = backup_chroma(source_dir=args.source, dest_tar_path=args.dest)
            print(f"[OK] Chroma snapshot created at: {path}")
            return 0

        elif args.command == "restore-chroma":
            path = restore_chroma(archive_path=args.archive, target_dir=args.target)
            print(f"[OK] Chroma restored to: {path}")
            return 0

        elif args.command == "verify":
            f = Path(args.file)
            if not f.exists():
                print(f"[ERROR] File not found: {f}", file=sys.stderr)
                return 1
            sha = compute_file_sha256(f)
            print(f"[OK] File verified: {f} ({f.stat().st_size} bytes)")
            print(f"     SHA-256: {sha}")
            return 0

    except Exception as e:
        print(f"[ERROR] Disaster recovery operation failed: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
