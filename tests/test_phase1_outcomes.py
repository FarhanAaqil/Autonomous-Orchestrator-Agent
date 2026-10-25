from types import SimpleNamespace
from unittest.mock import patch, MagicMock
import pytest
from orchestrator_core.core import approval_gate as gate
from orchestrator_core.exceptions import ApprovalAlreadyExecutedError
from orchestrator_core.runner.loop import _default_llm_call

EMAIL = {"to_email": "person@example.org", "subject": "Review", "body": "Draft"}


def ready(db):
    aid = gate.request_approval("send_email", EMAIL, db)
    digest = db.execute("SELECT payload_hash FROM approvals WHERE id=?", (aid,)).fetchone()[0]
    gate.approve(aid, db, digest)
    return aid


def test_simulation_is_not_delivery_and_cannot_repeat(db):
    aid = ready(db)
    result = gate.execute_approved(aid, db)
    assert result["status"] == "simulated"
    assert db.execute("SELECT outcome FROM execution_attempts").fetchone()[0] == "simulated"
    with pytest.raises(ApprovalAlreadyExecutedError):
        gate.execute_approved(aid, db)


@pytest.mark.parametrize("failure,expected", [("login", "failed"), ("send_message", "outcome_unknown"), (None, "submitted")])
def test_smtp_acceptance_and_failure_stages(failure, expected):
    settings = SimpleNamespace(action_execution_mode="live", enable_real_email=True,
                               email_address="owner@example.org", email_app_password="fake")
    server = MagicMock()
    server.send_message.return_value = {}
    if failure:
        getattr(server, failure).side_effect = TimeoutError("injected")
    with patch.object(gate, "get_settings", return_value=settings), patch("smtplib.SMTP_SSL", return_value=server):
        result = gate._dispatch_action("send_email", EMAIL, "test-id")
    assert result["outcome"] == expected


def test_crash_after_claim_is_reconcilable_without_resending(db):
    aid = ready(db)
    with patch.object(gate, "_dispatch_action", side_effect=KeyboardInterrupt):
        with pytest.raises(KeyboardInterrupt):
            gate.execute_approved(aid, db)
    row = db.execute("SELECT * FROM execution_attempts").fetchone()
    assert row["outcome"] == "outcome_unknown" and row["finished_at"] is None
    with db:
        db.execute("UPDATE execution_attempts SET started_at='2020-01-01T00:00:00+00:00'")
    result = gate.reconcile_execution(aid, "confirmed", "Provider log confirms receipt 12345", db)
    assert result["status"] == "confirmed"
    with pytest.raises(ApprovalAlreadyExecutedError):
        gate.execute_approved(aid, db)


def test_local_commit_failure_preserves_uncertain_attempt(db):
    aid = ready(db)
    real_audit = gate.log_audit
    def audit(*args, **kwargs):
        if kwargs.get("event") == "execution_outcome":
            raise RuntimeError("commit unavailable")
        return real_audit(*args, **kwargs)
    with patch.object(gate, "_dispatch_action", return_value={"outcome": "submitted"}), patch.object(gate, "log_audit", side_effect=audit):
        with pytest.raises(RuntimeError):
            gate.execute_approved(aid, db)
    assert db.execute("SELECT outcome FROM execution_attempts").fetchone()[0] == "outcome_unknown"
    assert db.execute("SELECT status FROM approvals WHERE id=?", (aid,)).fetchone()[0] == "executing"


def test_missing_model_key_cannot_invent_completed_work():
    settings = SimpleNamespace(groq_api_key=None)
    with patch("orchestrator_core.runner.loop.get_settings", return_value=settings):
        with pytest.raises(RuntimeError, match="credentials"):
            _default_llm_call([{"role": "user", "content": "Do the task"}])
