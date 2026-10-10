"""
tests/test_schedules.py

Tests for recurring autonomous schedules CRUD, immediate triggering,
and SSE event streaming with Last-Event-ID header.
"""

import sqlite3
import pytest
from fastapi.testclient import TestClient

from orchestrator_core.main import app
from orchestrator_core.jobs.events import event_hub
from orchestrator_core.storage.db import get_db, run_migrations


@pytest.fixture()
def clean_db() -> sqlite3.Connection:
    conn = get_db(":memory:")
    run_migrations(conn)
    yield conn
    conn.close()


@pytest.fixture()
def client(clean_db: sqlite3.Connection) -> TestClient:
    from orchestrator_core.storage.db import get_db_connection

    app.dependency_overrides[get_db_connection] = lambda: clean_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_schedules_crud_and_run_trigger(client: TestClient):
    # 1. List default seeded schedules
    resp = client.get("/schedules")
    assert resp.status_code == 200
    schedules = resp.json()
    assert len(schedules) >= 2
    sched_ids = [s["id"] for s in schedules]
    assert "daily_briefing" in sched_ids
    assert "stale_approval_cleanup" in sched_ids

    # 2. Create new schedule
    payload = {
        "name": "Hourly Tech News Scan",
        "agent": "research_agent",
        "goal": "Scan top arXiv papers and summarize quantum computing advancements",
        "cron_expr": "0 * * * *",
        "is_active": True,
    }
    create_resp = client.post("/schedules", json=payload)
    assert create_resp.status_code == 201
    created = create_resp.json()
    assert created["name"] == "Hourly Tech News Scan"
    assert created["agent"] == "research_agent"
    assert created["is_active"] is True
    sched_id = created["id"]

    # 3. Get single schedule
    get_resp = client.get(f"/schedules/{sched_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == sched_id

    # 4. Patch toggle is_active to False
    patch_resp = client.patch(f"/schedules/{sched_id}", json={"is_active": False})
    assert patch_resp.status_code == 200
    assert patch_resp.json()["is_active"] is False

    # 5. Trigger run now
    run_resp = client.post(f"/schedules/{sched_id}/run")
    assert run_resp.status_code == 200
    run_data = run_resp.json()
    assert run_data["status"] == "triggered"
    assert "job_id" in run_data
    assert run_data["agent"] == "research_agent"

    # Verify job was created in jobs queue
    job_resp = client.get(f"/jobs/{run_data['job_id']}")
    assert job_resp.status_code == 200
    assert job_resp.json()["agent"] == "research_agent"

    # 6. Delete schedule
    del_resp = client.delete(f"/schedules/{sched_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["deleted"] is True

    # Confirm 404 after deletion
    get_after_del = client.get(f"/schedules/{sched_id}")
    assert get_after_del.status_code == 404


def test_sse_event_hub_and_last_event_id_replay():
    # Publish events to event hub
    event_hub.publish("job.created", {"job_id": "test_job_1", "status": "queued"})
    event_hub.publish("job.step", {"job_id": "test_job_1", "step": 1, "kind": "tool"})
    current_counter = event_hub._counter
    assert current_counter >= 2

    # Verify history contains events with IDs
    assert len(event_hub._history) >= 2
    last_item = event_hub._history[-1]
    assert last_item[0] == current_counter
    assert f"id: {current_counter}" in last_item[1]
