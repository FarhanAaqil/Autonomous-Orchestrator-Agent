"""Database-authoritative schedules. Missed occurrences coalesce into one run."""
import logging
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from apscheduler.triggers.cron import CronTrigger

from orchestrator_core.storage.transactions import transaction

logger = logging.getLogger(__name__)
_scheduler = None


def next_occurrence(expression, zone, after):
    trigger = CronTrigger.from_crontab(expression, timezone=ZoneInfo(zone))
    fire = trigger.get_next_fire_time(None, after + timedelta(microseconds=1))
    if fire is None:
        raise ValueError('Cron expression has no next occurrence')
    return fire.astimezone(timezone.utc).isoformat()


def tick(db, now=None):
    from orchestrator_core.jobs.service import JobService
    from orchestrator_core.jobs.dependencies import reconcile
    from orchestrator_core.jobs.reaper import reap_zombies
    now = now or datetime.now(timezone.utc)
    queued = []
    for candidate in db.execute('SELECT * FROM schedules WHERE is_active=1').fetchall():
        with transaction(db):
            # A row lock also serializes concurrent edits/deletions on PostgreSQL.
            row = db.execute('UPDATE schedules SET updated_at=updated_at WHERE id=? AND is_active=1 RETURNING *', (candidate['id'],)).fetchone()
            if not row:
                continue
            if not row['next_run_at']:
                db.execute('UPDATE schedules SET next_run_at=? WHERE id=?',
                           (next_occurrence(row['cron_expr'], row['timezone'], now), row['id']))
                continue
            if row['next_run_at'] > now.isoformat():
                continue
            due = row['next_run_at']
            following = next_occurrence(row['cron_expr'], row['timezone'], now)
            if db.execute('SELECT 1 FROM schedule_occurrences WHERE schedule_id=? AND due_at=?', (row['id'], due)).fetchone():
                db.execute('UPDATE schedules SET next_run_at=? WHERE id=?', (following, row['id']))
                continue
            job = JobService.create_job(row['agent'], row['goal'], db, schedule_id=row['id'])
            db.execute('INSERT INTO schedule_occurrences VALUES (?,?,?)', (row['id'], due, job.id))
            db.execute('UPDATE schedules SET last_run_at=?,next_run_at=? WHERE id=?', (now.isoformat(), following, row['id']))
            queued.append(job.id)
    with transaction(db):
        db.execute("UPDATE approvals SET status='expired',version=version+1 WHERE status IN ('pending','approved') AND expires_at<?", (now.isoformat(),))
    reap_zombies(db)
    reconcile(db)
    from orchestrator_core.memory.context import synchronize_vectors
    synchronize_vectors(db)
    return queued


def _tick():
    from orchestrator_core.storage.db import get_db
    db = get_db()
    try:
        tick(db)
    finally:
        db.close()


def start_scheduler(daily_briefing_hour=8):
    global _scheduler
    from apscheduler.schedulers.background import BackgroundScheduler
    _scheduler = BackgroundScheduler(timezone='UTC')
    _scheduler.add_job(_tick, 'interval', seconds=5, max_instances=1, coalesce=True)
    _scheduler.start()


def stop_scheduler():
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
