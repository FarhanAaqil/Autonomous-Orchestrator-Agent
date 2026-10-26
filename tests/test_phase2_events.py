import pytest
from orchestrator_core.jobs.service import JobService
from orchestrator_core.storage.transactions import transaction


def test_events_commit_and_rollback_with_job(db):
    with pytest.raises(RuntimeError):
        with transaction(db):
            JobService.create_job('general_chat', 'Rollback event', db)
            raise RuntimeError('interrupted')
    assert db.execute('SELECT COUNT(*) FROM job_events').fetchone()[0] == 0
    job = JobService.create_job('general_chat', 'Durable event', db)
    event = db.execute('SELECT * FROM job_events').fetchone()
    assert event['event'] == 'job.created' and job.id in event['data_json']


@pytest.mark.asyncio
async def test_revoked_stream_closes(monkeypatch):
    from orchestrator_core.jobs.events import JobEventHub
    hub = JobEventHub()
    monkeypatch.setattr(hub, 'read', lambda *_: (None, None))
    messages = [item async for item in hub.subscribe(session_token='revoked')]
    assert any('session.expired' in item for item in messages)
