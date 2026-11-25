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


def test_sse_event_hub_and_last_event_id_replay(tmp_path, monkeypatch):
    from orchestrator_core.jobs.service import JobService
    path = str(tmp_path / 'events.db')
    conn = get_db(path)
    run_migrations(conn)
    job = JobService.create_job('research_agent', 'Replay persisted work', conn)
    cursor = conn.execute('SELECT MAX(id) FROM job_events').fetchone()[0]
    JobService.cancel_job(job.id, conn)
    conn.close()
    monkeypatch.setattr('orchestrator_core.storage.db.get_db', lambda: get_db(path))
    bounds, rows = event_hub.read(cursor)
    assert bounds[1] > cursor
    assert rows and all(row['id'] > cursor for row in rows)
    assert all(job.id in row['data_json'] for row in rows)


@pytest.mark.anyio
async def test_sse_endpoint_query_and_header_reconnect(monkeypatch):
    from starlette.requests import Request
    from orchestrator_core.routes.jobs import stream_job_events
    received = []
    async def stream(last_event_id=None, session_token=None, owner=None):
        received.append((last_event_id, session_token, owner))
        yield 'event: fixture\ndata: {}\n\n'
    monkeypatch.setattr(event_hub, 'subscribe', stream)
    request = Request({'type': 'http', 'headers': [(b'cookie', b'orchestrator_session=fixture')]})
    for header, query, expected in [(None, '12', '12'), ('13', '12', '13')]:
        response = stream_job_events(request, last_event_id=header, last_event_id_query=query, owner="fixture-owner")
        assert 'fixture' in await response.body_iterator.__anext__()
        assert received[-1] == (expected, 'fixture', 'fixture-owner')
        await response.body_iterator.aclose()
