import pytest
from cryptography.fernet import Fernet, InvalidToken
from orchestrator_core.storage.postgres_backup import restore
from orchestrator_core.storage.backup import restore_chroma


def test_corrupt_encrypted_archive_never_connects(tmp_path, monkeypatch):
    archive = tmp_path/'bad.enc'
    archive.write_bytes(b'corrupt')
    monkeypatch.setattr('orchestrator_core.storage.postgres.connect', lambda *a, **k: pytest.fail('Connected before authentication'))
    with pytest.raises(InvalidToken):
        restore(archive, 'postgresql://unused', Fernet.generate_key())


def test_invalid_vector_archive_preserves_live_data(tmp_path):
    live = tmp_path/'vectors'
    live.mkdir()
    (live/'known').write_text('keep me')
    archive = tmp_path/'bad.tar.gz'
    archive.write_bytes(b'corrupt')
    with pytest.raises(Exception):
        restore_chroma(archive, live)
    assert (live/'known').read_text() == 'keep me'
