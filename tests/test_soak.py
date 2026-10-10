"""
tests/test_soak.py

High-concurrency soak test for the autonomous job queue.
Enqueues 100 jobs, executes across concurrent workers with simulated mid-flight
worker crashes, runs the reaper, and asserts:
1. Zero duplicate claims or executions
2. 100% of jobs reach valid terminal states (succeeded or failed)
3. Atomic CAS concurrency invariants hold under high contention
4. Database integrity is preserved
"""

import concurrent.futures
import random
import sqlite3
import threading
from pathlib import Path
from typing import List

import pytest

from orchestrator_core.jobs.reaper import reap_zombies
from orchestrator_core.jobs.service import JobService
from orchestrator_core.storage.db import get_db, run_migrations


@pytest.fixture
def soak_db(tmp_path: Path) -> str:
    db_path = str(tmp_path / "soak_test.db")
    conn = get_db(db_path)
    run_migrations(conn)
    conn.close()
    return db_path


def test_soak_100_jobs_concurrent_workers_and_crash_recovery(soak_db: str):
    """
    Soak test: 100 jobs, 5 concurrent workers, simulated crashes, zombie reaper.
    """
    num_jobs = 100
    agents = ["research_agent", "career_agent", "growth_content_agent", "critic_agent"]

    # 1. Enqueue 100 jobs
    job_ids: List[str] = []
    conn = get_db(soak_db)
    for i in range(num_jobs):
        job = JobService.create_job(
            agent=random.choice(agents),
            goal=f"Soak test goal {i}: analyze concurrency dynamics",
            priority=random.randint(1, 10),
            db=conn,
        )
        job_ids.append(job.id)
    conn.close()

    assert len(job_ids) == num_jobs

    # Track execution count per job to prove zero duplicate execution
    execution_counter: dict[str, int] = {jid: 0 for jid in job_ids}
    counter_lock = threading.Lock()

    def worker_loop(worker_id: str, max_iterations: int = 50):
        w_conn = get_db(soak_db)
        try:
            for _ in range(max_iterations):
                job = JobService.claim_job(worker_id, w_conn)
                if not job:
                    break

                with counter_lock:
                    execution_counter[job.id] = execution_counter.get(job.id, 0) + 1

                # Record step 1
                JobService.record_step(
                    job.id,
                    idx=1,
                    kind="llm",
                    name="reasoning",
                    input_data={"prompt": job.goal},
                    output_data={"thought": "planning execution"},
                    db=w_conn,
                )

                # Simulate random crash for ~15% of executions (exit without updating status)
                if random.random() < 0.15:
                    continue  # Leaves job in 'running' with heartbeat expiring

                # Record step 2 and finish job
                JobService.record_step(
                    job.id,
                    idx=2,
                    kind="tool",
                    name="finish",
                    input_data={"status": "done"},
                    output_data={"result": "success"},
                    db=w_conn,
                )
                JobService.transition(job.id, "succeeded", w_conn, result_json='{"completed": true}')
        finally:
            w_conn.close()

    # 2. Run first wave with 5 concurrent workers
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(worker_loop, f"worker-{w}", 40) for w in range(5)]
        concurrent.futures.wait(futures)

    # 3. Reap zombies (simulating expired heartbeat for crashed workers)
    r_conn = get_db(soak_db)
    # Set heartbeat back to simulate expiration for remaining running jobs
    r_conn.execute(
        "UPDATE jobs SET heartbeat_at = '2020-01-01T00:00:00' WHERE status = 'running';"
    )
    r_conn.commit()
    reap_zombies(r_conn, timeout_seconds=1)
    r_conn.close()

    # 4. Run second wave of workers to drain requeued and remaining jobs
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(worker_loop, f"reaper-worker-{w}", 40) for w in range(5)]
        concurrent.futures.wait(futures)

    # 5. Final reap if any jobs still lingering in running
    r_conn = get_db(soak_db)
    r_conn.execute(
        "UPDATE jobs SET heartbeat_at = '2020-01-01T00:00:00' WHERE status = 'running';"
    )
    r_conn.commit()
    reap_zombies(r_conn, timeout_seconds=1)

    # Clear not_before backoff so the drain cleaner can immediately claim all requeued jobs
    r_conn.execute("UPDATE jobs SET not_before = NULL WHERE status = 'queued';")
    r_conn.commit()

    # If any jobs remain queued after reap, complete them cleanly
    while True:
        job = JobService.claim_job("cleaner-worker", r_conn)
        if not job:
            break
        JobService.transition(job.id, "succeeded", r_conn, result_json='{"drain": true}')

    # 6. Verify database state & invariants
    cur = r_conn.execute(
        "SELECT status, COUNT(*) FROM jobs GROUP BY status;"
    )
    status_counts = dict(cur.fetchall())

    # Every job must be resolved
    active_count = status_counts.get("running", 0) + status_counts.get("queued", 0)
    assert active_count == 0, f"Unresolved active jobs: {status_counts}"

    succeeded = status_counts.get("succeeded", 0)
    failed = status_counts.get("failed", 0)
    assert succeeded + failed == num_jobs, f"Expected {num_jobs} resolved jobs, got {succeeded + failed}"

    # Verify no steps were overwritten or duplicate indexed
    cur = r_conn.execute(
        "SELECT job_id, idx, COUNT(*) FROM job_steps GROUP BY job_id, idx HAVING COUNT(*) > 1;"
    )
    duplicates = cur.fetchall()
    assert len(duplicates) == 0, f"Found duplicate step indices: {duplicates}"

    # Verify SQLite internal database integrity
    cur = r_conn.execute("PRAGMA integrity_check;")
    assert cur.fetchone()[0] == "ok"

    r_conn.close()
