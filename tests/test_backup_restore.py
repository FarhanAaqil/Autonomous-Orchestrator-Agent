"""
tests/test_backup_restore.py

Tests for zero-downtime SQLite and ChromaDB disaster recovery backup and restore.
Verifies atomicity, point-in-time recovery, and corrupted file rejection.
"""

import json
import sqlite3
from pathlib import Path

import pytest

from orchestrator_core.storage.backup import (
    backup_chroma,
    backup_sqlite,
    compute_file_sha256,
    create_full_system_snapshot,
    restore_chroma,
    restore_sqlite,
)
from orchestrator_core.storage.db import run_migrations


@pytest.fixture
def test_db_path(tmp_path: Path) -> Path:
    db_file = tmp_path / "original.db"
    conn = sqlite3.connect(str(db_file))
    run_migrations(conn)
    conn.execute(
        "INSERT OR REPLACE INTO system_flags (key, value) VALUES ('test_flag', 'initial_val');"
    )
    conn.commit()
    conn.close()
    return db_file


def test_backup_sqlite_creates_valid_copy(test_db_path: Path, tmp_path: Path):
    dest_backup = tmp_path / "backups" / "test_backup.db"
    backup_path = backup_sqlite(source_path=test_db_path, dest_path=dest_backup)

    assert backup_path.exists()
    assert dest_backup.stat().st_size > 0

    # Verify backup contents
    chk = sqlite3.connect(str(dest_backup))
    cur = chk.execute("SELECT value FROM system_flags WHERE key='test_flag';")
    row = cur.fetchone()
    chk.close()
    assert row is not None
    assert row[0] == "initial_val"


def test_restore_sqlite_recovers_data(test_db_path: Path, tmp_path: Path):
    backup_file = tmp_path / "backup_before_mutation.db"
    backup_sqlite(source_path=test_db_path, dest_path=backup_file)

    # Mutate original database
    conn = sqlite3.connect(str(test_db_path))
    conn.execute("UPDATE system_flags SET value='mutated_val' WHERE key='test_flag';")
    conn.commit()
    conn.close()

    # Verify mutation took effect
    conn = sqlite3.connect(str(test_db_path))
    assert conn.execute("SELECT value FROM system_flags WHERE key='test_flag';").fetchone()[0] == "mutated_val"
    conn.close()

    # Restore from backup
    restore_sqlite(backup_path=backup_file, target_path=test_db_path)

    # Verify restoration recovered original value
    conn = sqlite3.connect(str(test_db_path))
    val = conn.execute("SELECT value FROM system_flags WHERE key='test_flag';").fetchone()[0]
    conn.close()
    assert val == "initial_val"


def test_restore_sqlite_rejects_corrupted_file(tmp_path: Path):
    corrupt_file = tmp_path / "corrupt.db"
    corrupt_file.write_bytes(b"CORRUPT DATA INVALID SQLITE DATABASE HEADER NOT RECOGNIZED")

    target_file = tmp_path / "target.db"
    with pytest.raises(ValueError, match="Corrupt backup file"):
        restore_sqlite(backup_path=corrupt_file, target_path=target_file)


def test_chroma_backup_and_restore_roundtrip(tmp_path: Path):
    source_chroma = tmp_path / "chroma_source"
    source_chroma.mkdir()
    (source_chroma / "chroma.sqlite3").write_text("mock chroma sqlite contents")
    (source_chroma / "index_meta.json").write_text('{"collection": "episodes"}')

    dest_tar = tmp_path / "chroma.tar.gz"
    backup_chroma(source_dir=source_chroma, dest_tar_path=dest_tar)

    assert dest_tar.exists()
    assert dest_tar.stat().st_size > 0

    restore_target = tmp_path / "chroma_restored"
    restore_chroma(archive_path=dest_tar, target_dir=restore_target)

    assert (restore_target / "chroma.sqlite3").exists()
    assert (restore_target / "index_meta.json").exists()
    assert (restore_target / "index_meta.json").read_text() == '{"collection": "episodes"}'


def test_full_system_snapshot_creates_manifest(test_db_path: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(test_db_path))
    snapshot_dir = tmp_path / "full_snapshot"

    res = create_full_system_snapshot(output_dir=snapshot_dir)
    assert Path(res["snapshot_dir"]).exists()

    manifest_file = snapshot_dir / "manifest.json"
    assert manifest_file.exists()

    manifest = json.loads(manifest_file.read_text())
    assert manifest["version"] == "1.0.0"
    assert manifest["rpo"] == "1h"
    assert manifest["rto"] == "<30s"
    assert "sqlite" in manifest
    assert "chroma" in manifest
    assert len(manifest["sqlite"]["sha256"]) == 64

    # Verify sha256 checksum
    db_file = snapshot_dir / manifest["sqlite"]["path"]
    assert compute_file_sha256(db_file) == manifest["sqlite"]["sha256"]
