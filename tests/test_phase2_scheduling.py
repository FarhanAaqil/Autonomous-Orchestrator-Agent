from datetime import datetime, timezone
import pytest
from orchestrator_core.core.scheduler import next_occurrence, tick
from orchestrator_core.storage.transactions import transaction
from orchestrator_core.jobs.service import JobService


def test_due_occurrence_is_queued_once(db):
    db.execute('DELETE FROM schedules')
    db.execute("INSERT INTO schedules (id,name,agent,goal,cron_expr,next_run_at) VALUES ('due','Due','general_chat','Test','0 8 * * *','2026-01-01T08:00:00+00:00')")
    db.commit()
    now = datetime(2026, 1, 2, 9, tzinfo=timezone.utc)
    assert len(tick(db, now)) == 1
    assert tick(db, now) == []
    assert db.execute('SELECT COUNT(*) FROM schedule_occurrences').fetchone()[0] == 1
    db.execute("UPDATE schedules SET is_active=0,next_run_at='2000-01-01' WHERE id='due'")
    db.commit()
    assert tick(db, now) == []


def test_utc_india_and_dst_timezones():
    after = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert next_occurrence('0 8 * * *', 'UTC', after) == '2026-01-01T08:00:00+00:00'
    assert next_occurrence('0 8 * * *', 'Asia/Kolkata', after) == '2026-01-01T02:30:00+00:00'
    summer = datetime(2026, 7, 1, tzinfo=timezone.utc)
    assert next_occurrence('0 8 * * *', 'America/New_York', summer) == '2026-07-01T12:00:00+00:00'
    with pytest.raises(ValueError):
        next_occurrence('invalid', 'UTC', after)


def test_nested_job_creation_rolls_back_with_occurrence(db):
    with pytest.raises(RuntimeError):
        with transaction(db):
            JobService.create_job('general_chat', 'Must roll back', db)
            raise RuntimeError('occurrence insert failed')
    assert db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0] == 0
