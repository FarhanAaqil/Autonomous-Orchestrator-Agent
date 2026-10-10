"""
tests/test_budget_and_alarms.py

Tests for daily cost tracking, budget ceilings, and alarm notifications.
Verifies that:
1. Daily budget limits in system_flags are strictly enforced.
2. Exceeding daily budget aborts job execution within 1 turn.
3. System budget alarm events are published and audit log records the incident.
"""

import sqlite3
from pathlib import Path

import pytest

from orchestrator_core.exceptions import BudgetExceededError
from orchestrator_core.jobs.events import event_hub
from orchestrator_core.jobs.service import JobService
from orchestrator_core.runner.caps import check_guards
from orchestrator_core.runner.loop import run_job
from orchestrator_core.storage.db import get_db, run_migrations


@pytest.fixture
def budget_db(tmp_path: Path) -> sqlite3.Connection:
    db_path = str(tmp_path / "budget_test.db")
    conn = get_db(db_path)
    run_migrations(conn)
    return conn


def test_budget_exceeded_guard_raises_error(budget_db: sqlite3.Connection):
    # Set daily budget ceiling to $2.00
    budget_db.execute("INSERT OR REPLACE INTO system_flags (key, value) VALUES ('daily_budget_usd', '2.00');")
    budget_db.commit()

    # Create a job with cost exceeding $2.00 today
    job = JobService.create_job(
        agent="research_agent",
        goal="Expensive benchmark run",
        db=budget_db,
    )

    # Insert cost into a prior completed job
    budget_db.execute(
        "UPDATE jobs SET cost_usd = 2.50 WHERE id = ?",
        (job.id,),
    )
    budget_db.commit()

    fresh_job = JobService.get_job(job.id, budget_db)
    assert fresh_job is not None

    with pytest.raises(BudgetExceededError) as exc_info:
        check_guards(fresh_job, budget_db)

    assert exc_info.value.current_cost >= 2.00
    assert exc_info.value.budget_limit == 2.00


def test_budget_alarm_event_and_job_abort_in_loop(budget_db: sqlite3.Connection):
    # Set low daily budget
    budget_db.execute("INSERT OR REPLACE INTO system_flags (key, value) VALUES ('daily_budget_usd', '1.00');")
    budget_db.commit()

    # Pre-populate existing spent budget today
    dummy_job = JobService.create_job(agent="career_agent", goal="prior run", db=budget_db)
    budget_db.execute("UPDATE jobs SET cost_usd = 1.50 WHERE id = ?", (dummy_job.id,))
    budget_db.commit()

    # Create new job that attempts to run
    new_job = JobService.create_job(agent="critic_agent", goal="run under exhausted budget", db=budget_db)

    # Clear history before run
    event_hub._history.clear()

    # Run the job loop
    final_job = run_job(new_job, db=budget_db, worker_id="budget-worker-1")

    # Verify job was failed immediately
    assert final_job.status == "failed"
    assert "Daily budget exceeded" in (final_job.error or "")

    # Verify alarm event was published to event_hub history
    alarm_events = [
        msg for eid, msg in event_hub._history if "system.budget_alarm" in msg
    ]
    assert len(alarm_events) >= 1
    assert new_job.id in alarm_events[0]
    assert "Daily budget exceeded" in alarm_events[0]

    # Verify audit log recorded the event
    cur = budget_db.execute(
        "SELECT event, detail_json FROM audit_log WHERE event = 'budget_ceiling_exceeded';"
    )
    row = cur.fetchone()
    assert row is not None
    assert row[0] == "budget_ceiling_exceeded"
