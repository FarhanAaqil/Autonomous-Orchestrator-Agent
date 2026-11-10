from concurrent.futures import ThreadPoolExecutor
from threading import Event
import time

from fastapi.testclient import TestClient
from orchestrator_core.storage.db import get_db_connection
from orchestrator_core.jobs.service import JobService
from orchestrator_core.jobs.background import enqueue, run_background_job


def test_pipeline_submission_is_durable(db, monkeypatch):
    from orchestrator_core.main import app
    app.dependency_overrides[get_db_connection] = lambda: db
    try:
        response = TestClient(app).post('/pipeline/research', json={'command':'Research locally'})
        assert response.status_code == 202
        job = JobService.get_job(response.json()['job_id'], db)
        assert job.status == 'queued' and job.work_kind == 'pipeline'
        monkeypatch.setattr('orchestrator_core.core.pipeline_engine.run_pipeline', lambda *_: 'known-run')
        result = run_background_job(job, db)
        assert result.status == 'succeeded' and 'known-run' in result.result_json
    finally:
        app.dependency_overrides.clear()


def test_health_remains_responsive_during_routing(db, monkeypatch):
    from orchestrator_core.main import app
    from orchestrator_core.models import RouterResult
    entered, release = Event(), Event()
    def slow(*args, **kwargs):
        entered.set()
        release.wait(2)
        return RouterResult(agent='general_chat_agent', confidence=0.9, reasoning='local test')
    monkeypatch.setattr('orchestrator_core.routes.route.classify', slow)
    app.dependency_overrides[get_db_connection] = lambda: db
    try:
        with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(client.post, '/route', json={'command':'hello'})
            assert entered.wait(1)
            start = time.monotonic()
            assert client.get('/health').status_code == 200
            assert time.monotonic()-start < 0.5
            release.set()
            assert pending.result().status_code == 200
    finally:
        release.set()
        app.dependency_overrides.clear()
