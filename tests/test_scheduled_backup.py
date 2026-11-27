import json
import pytest
from orchestrator_core.storage import scheduled_backup as job


def test_retention_only_removes_owned_archives_after_success(tmp_path, monkeypatch):
    old = tmp_path / ('toji-20200101T000000Z-' + 'a'*32 + '.fernet')
    old.write_bytes(b'old encrypted fixture')
    unrelated = tmp_path / 'personal-backup.fernet'
    unrelated.write_bytes(b'keep')
    def backup(url, target, key):
        target.write_bytes(b'new encrypted fixture')
        return {'bytes': 21, 'backup_seconds': 0.1}
    monkeypatch.setattr(job, 'backup', backup)
    result = job.run(tmp_path, 'fixture-url', 'fixture-key', 30)
    assert result['removed'] == 1 and not old.exists()
    assert unrelated.read_bytes() == b'keep'
    assert len(list(tmp_path.glob('toji-*.fernet'))) == 1
    assert json.loads((tmp_path/'last-success.json').read_text())['retention_days'] == 30


def test_failed_backup_preserves_archives_and_success_marker(tmp_path, monkeypatch):
    old = tmp_path / ('toji-20200101T000000Z-' + 'b'*32 + '.fernet')
    old.write_bytes(b'keep')
    marker = tmp_path / 'last-success.json'
    marker.write_text('{"old": true}')
    def fail(*args):
        raise RuntimeError('private database details')
    monkeypatch.setattr(job, 'backup', fail)
    with pytest.raises(RuntimeError):
        job.run(tmp_path, 'url', 'key')
    assert old.exists() and marker.read_text() == '{"old": true}'


def test_scheduled_failures_do_not_log_credentials(monkeypatch, capsys):
    monkeypatch.setenv('BACKUP_DIRECTORY', 'unused')
    monkeypatch.setenv('MIGRATION_DATABASE_URL', 'private-url')
    monkeypatch.setenv('BACKUP_ENCRYPTION_KEY', 'private-key')
    def fail(*args):
        raise RuntimeError('private-url private-key')
    monkeypatch.setattr(job, 'run', fail)
    assert job.main() == 1
    output = capsys.readouterr().out
    assert 'private-' not in output and 'backup_failed' in output
