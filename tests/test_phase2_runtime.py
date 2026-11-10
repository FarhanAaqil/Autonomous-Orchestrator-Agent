from datetime import datetime, timezone
from types import SimpleNamespace
from orchestrator_core.runtime import readiness


def test_readiness_requires_worker_scheduler_and_sandbox(db, monkeypatch):
    monkeypatch.setenv('SANDBOX_BROWSER_URL', 'http://sandbox.invalid')
    monkeypatch.setattr('httpx.get', lambda *a, **k: SimpleNamespace(is_success=True))
    assert not all(readiness(db).values())
    for role in ('worker', 'scheduler'):
        db.execute('INSERT INTO service_heartbeats VALUES (?,?)', (role, datetime.now(timezone.utc).isoformat()))
    db.commit()
    assert all(readiness(db).values())
    monkeypatch.setattr('httpx.get', lambda *a, **k: SimpleNamespace(is_success=False))
    assert readiness(db)['sandbox'] is False


def test_expired_worker_heartbeat_fails_readiness(db, monkeypatch):
    monkeypatch.delenv('SANDBOX_BROWSER_URL', raising=False)
    db.execute("INSERT INTO service_heartbeats VALUES ('worker','2000-01-01')")
    db.commit()
    assert readiness(db)['worker'] is False
