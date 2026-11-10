import os
import pytest
from cryptography.fernet import Fernet
from orchestrator_core.storage.postgres import connect, migrate
from orchestrator_core.storage.postgres_backup import backup, restore


def test_encrypted_restore_into_fresh_database(tmp_path):
    source = os.environ.get('PHASE2_TEST_DATABASE_URL')
    target = os.environ.get('PHASE2_RESTORE_DATABASE_URL')
    if not source or not target:
        pytest.skip('Disposable source and empty restore database URLs required')
    db = connect(source, pooled=False)
    try:
        migrate(db)
        with db:
            db.execute("INSERT INTO system_flags(key,value) VALUES ('restore_evidence','known-value') ON CONFLICT(key) DO UPDATE SET value=excluded.value")
    finally:
        db.close()
    key = Fernet.generate_key()
    archive = tmp_path/'backup.enc'
    created = backup(source, archive, key)
    restored = restore(archive, target, key)
    assert not archive.read_bytes().startswith(b'PGDMP')
    db = connect(target, pooled=False)
    try:
        assert db.execute("SELECT value FROM system_flags WHERE key='restore_evidence'").fetchone()[0] == 'known-value'
    finally:
        db.close()
    print(f"Measured backup={created['backup_seconds']:.2f}s restore={restored['restore_seconds']:.2f}s")
    with pytest.raises(ValueError, match='empty destination'):
        restore(archive, target, key)
