import json
import pytest
from unittest.mock import patch, Mock
from fastapi.testclient import TestClient
from orchestrator_core.core.policy import require_execution, run_handler
from orchestrator_core.core.approval_gate import request_approval
from orchestrator_core.exceptions import AgentDisabledError, KillSwitchActiveError, SecurityPolicyViolationError
from orchestrator_core.jobs.service import JobService
from orchestrator_core.runner.loop import run_job
from orchestrator_core.main import app
from orchestrator_core.storage.db import get_db, get_db_connection
from orchestrator_core.models import RouterResult


def test_critic_direct_proposal_denied(db):
    job = JobService.create_job("critic_agent", "Review", db)
    job = JobService.claim_job("test-worker", db)
    result = run_job(job, db, worker_id="test-worker", llm_client=lambda _: json.dumps({"action": "propose", "action_input": {
        "action_type": "send_email", "payload": {"to": "person@example.org", "subject": "Hello", "body": "Draft"}}}))
    assert result.status == "failed"
    assert db.execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 0


def test_disabled_agent_streaming_never_runs():
    def disabled_db():
        db = get_db(":memory:")
        with db:
            db.execute("INSERT INTO system_flags(key,value) VALUES('agent_enabled_career_agent','0')")
        return db
    handler = Mock()
    with patch("orchestrator_core.routes.dispatch.get_db", side_effect=disabled_db), patch("orchestrator_core.routes.dispatch.classify", return_value=RouterResult(agent="career_agent", confidence=.99, reasoning="test")), patch("orchestrator_core.routes.dispatch._get_agent_registry", return_value={"career_agent": handler}):
        response = TestClient(app).post("/dispatch/stream", json={"command": "career review"})
    assert "AGENT_DISABLED" in response.text
    handler.assert_not_called()


def test_kill_switch_blocks_jobs_proposals_and_handlers(db):
    with db:
        db.execute("UPDATE system_flags SET value='on' WHERE key='kill_switch'")
    handler = Mock()
    for call in [lambda: JobService.create_job("email_agent", "draft", db),
                 lambda: run_handler(handler, "draft", db, "email_agent"),
                 lambda: request_approval("send_email", {"to": "person@example.org", "subject": "Hi", "body": "Draft"}, db)]:
        with pytest.raises(KillSwitchActiveError):
            call()
    handler.assert_not_called()
