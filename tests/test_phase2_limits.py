import time
import pytest
from orchestrator_core.core.usage import reserve
from orchestrator_core.core.provider import bounded_call
from orchestrator_core.exceptions import BudgetExceededError
from orchestrator_core.jobs.service import JobService
from orchestrator_core.runner.loop import run_job


def test_reservations_cannot_exceed_daily_limit(db):
    db.execute("UPDATE system_flags SET value='0.00001' WHERE key='daily_budget_usd'")
    db.commit()
    with pytest.raises(BudgetExceededError):
        reserve(db, [{'role': 'user', 'content': 'hello'}], 20)
    assert db.execute('SELECT COUNT(*) FROM provider_usage').fetchone()[0] == 0


def test_one_token_job_never_calls_provider(db):
    calls = []
    job = JobService.create_job('general_chat', 'Tiny budget', db, token_budget=1)
    result = run_job(job, db, llm_client=lambda _: calls.append(True))
    assert result.status == 'failed'
    assert not calls


def test_one_step_job_cannot_record_two_rows_and_succeed(db):
    job = JobService.create_job('general_chat', 'Tiny step limit', db, max_steps=1)
    result = run_job(job, db, llm_client=lambda _: '{"action":"final","action_input":{"summary":"done"}}')
    assert result.status == 'failed'
    assert len(JobService.get_steps(job.id, db)) == 1


def test_stalled_provider_has_bounded_deadline():
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        bounded_call(lambda: time.sleep(0.2), timeout=0.01)
    assert time.monotonic()-started < 0.15
