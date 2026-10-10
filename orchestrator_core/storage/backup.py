"""
orchestrator_core/storage/backup.py

Atomic SQLite database backup and ChromaDB vector snapshot management.
Provides zero-downtime, WAL-safe backups using SQLite's online backup API,
integrity verification, and safe point-in-time recovery.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sqlite3
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from orchestrator_core.config import get_settings

logger = logging.getLogger(__name__)


def compute_file_sha256(filepath: str | Path) -> str:
    """Calculate the SHA-256 hash of a file for integrity verification."""
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def backup_sqlite(
    source_path: Optional[str | Path] = None,
    dest_path: Optional[str | Path] = None,
) -> Path:
    """
    Perform an online, non-blocking backup of the SQLite database.

    Uses sqlite3.Connection.backup() which works concurrently with WAL mode
    without blocking readers or writers. Performs an integrity check on the
    resulting backup file.
    """
    settings = get_settings()
    src = Path(source_path or settings.database_path)

    if not src.exists() and str(src) != ":memory:":
        raise FileNotFoundError(f"Source database file not found: {src}")

    if dest_path is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_dir = Path("backups") / "sqlite"
        backup_dir.mkdir(parents=True, exist_ok=True)
        dest = backup_dir / f"aaqil_backup_{timestamp}.db"
    else:
        dest = Path(dest_path)
        dest.parent.mkdir(parents=True, exist_ok=True)

    src_conn = sqlite3.connect(str(src), check_same_thread=False)
    dest_conn = sqlite3.connect(str(dest), check_same_thread=False)

    try:
        # Perform atomic online backup
        with dest_conn:
            src_conn.backup(dest_conn)

        # Verify integrity of backup
        cur = dest_conn.execute("PRAGMA integrity_check;")
        row = cur.fetchone()
        if not row or row[0] != "ok":
            raise RuntimeError(f"Backup integrity check failed: {row[0] if row else 'null'}")

        logger.info("SQLite online backup created successfully: %s", dest)
        return dest.resolve()
    finally:
        src_conn.close()
        dest_conn.close()


def restore_sqlite(
    backup_path: str | Path,
    target_path: Optional[str | Path] = None,
) -> Path:
    """
    Restore database from a verified SQLite backup.

    Validates backup integrity first before applying to the target path.
    """
    backup = Path(backup_path)
    if not backup.exists():
        raise FileNotFoundError(f"Backup file not found: {backup}")

    # Validate backup integrity before restoring
    try:
        chk_conn = sqlite3.connect(str(backup))
        try:
            cur = chk_conn.execute("PRAGMA integrity_check;")
            row = cur.fetchone()
            if not row or row[0] != "ok":
                raise ValueError(f"Corrupt backup file: integrity check returned {row[0] if row else 'null'}")
        finally:
            chk_conn.close()
    except (sqlite3.DatabaseError, sqlite3.OperationalError) as e:
        raise ValueError(f"Corrupt backup file: {e}") from e

    settings = get_settings()
    target = Path(target_path or settings.database_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    backup_conn = sqlite3.connect(str(backup))
    target_conn = sqlite3.connect(str(target))
    try:
        with target_conn:
            backup_conn.backup(target_conn)
        logger.info("Restored database from %s to %s", backup, target)
        return target.resolve()
    finally:
        backup_conn.close()
        target_conn.close()


def backup_chroma(
    source_dir: Optional[str | Path] = None,
    dest_tar_path: Optional[str | Path] = None,
) -> Path:
    """
    Create a compressed tar snapshot of the ChromaDB directory.
    """
    src = Path(source_dir or "chroma_db")
    if not src.exists():
        src.mkdir(parents=True, exist_ok=True)

    if dest_tar_path is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_dir = Path("backups") / "chroma"
        backup_dir.mkdir(parents=True, exist_ok=True)
        dest = backup_dir / f"chroma_backup_{timestamp}.tar.gz"
    else:
        dest = Path(dest_tar_path)
        dest.parent.mkdir(parents=True, exist_ok=True)

    with tarfile.open(dest, "w:gz") as tar:
        for item in src.iterdir():
            tar.add(item, arcname=item.name)

    logger.info("ChromaDB snapshot created: %s", dest)
    return dest.resolve()


def restore_chroma(
    archive_path: str | Path,
    target_dir: Optional[str | Path] = None,
) -> Path:
    """
    Restore ChromaDB from a compressed tar archive.
    """
    archive = Path(archive_path)
    if not archive.exists():
        raise FileNotFoundError(f"Chroma archive not found: {archive}")

    target = Path(target_dir or "chroma_db")
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)

    with tarfile.open(archive, "r:gz") as tar:
        try:
            tar.extractall(path=target, filter="data")
        except TypeError:
            tar.extractall(path=target)

    logger.info("ChromaDB restored from %s to %s", archive, target)
    return target.resolve()


def create_full_system_snapshot(output_dir: Optional[str | Path] = None) -> dict[str, Any]:
    """
    Create a coordinated snapshot of both SQLite DB and ChromaDB vectors
    with metadata manifest.
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    base_dir = Path(output_dir or f"backups/snapshot_{timestamp}")
    base_dir.mkdir(parents=True, exist_ok=True)

    sqlite_backup = backup_sqlite(dest_path=base_dir / "aaqil.db")
    chroma_backup = backup_chroma(dest_tar_path=base_dir / "chroma.tar.gz")

    sqlite_sha256 = compute_file_sha256(sqlite_backup)
    chroma_sha256 = compute_file_sha256(chroma_backup)

    manifest = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sqlite": {
            "path": str(sqlite_backup.name),
            "sha256": sqlite_sha256,
            "size_bytes": sqlite_backup.stat().st_size,
        },
        "chroma": {
            "path": str(chroma_backup.name),
            "sha256": chroma_sha256,
            "size_bytes": chroma_backup.stat().st_size,
        },
        "version": "1.0.0",
        "rpo": "1h",
        "rto": "<30s",
    }

    manifest_path = base_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    return {
        "snapshot_dir": str(base_dir.resolve()),
        "manifest": manifest,
    }
