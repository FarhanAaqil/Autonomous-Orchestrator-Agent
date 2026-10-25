import sqlite3
from types import SimpleNamespace
from unittest.mock import patch
import pytest

from orchestrator_core.agents import email_agent, github_agent, growth_content_agent, linkedin_agent
from orchestrator_core.core import approval_gate as gate
from orchestrator_core.core.action_catalog import normalize_action
from orchestrator_core.exceptions import SecurityPolicyViolationError, KillSwitchActiveError
from orchestrator_core.storage.db import SCHEMA_SQL, run_migrations


@pytest.mark.parametrize("agent,command,draft", [
    (email_agent, "send email to person@example.org", "Subject: Hello\nA draft"),
    (github_agent, "create issue on owner/repo", "Title: Problem\nDetails"),
    (github_agent, "comment on issue #12 in owner/repo", "Comment text"),
    (growth_content_agent, "publish on hashnode", "# Article\nContent"),
    (linkedin_agent, "post on linkedin", "A post"),
])
def test_every_action_producer_emits_catalog_payload(agent, command, draft):
    with patch.object(agent, "_call_llm", return_value=draft):
        result = agent.handle(command)
    name, payload, target = normalize_action(result.action_type, result.metadata["approval_payload"])
    assert name and payload and target


@pytest.mark.parametrize("agent,command", [
    (email_agent, "send email about the meeting"),
    (github_agent, "create issue about a problem"),
    (github_agent, "comment on issue in owner/repo"),
])
def test_producer_never_invents_a_recipient(agent, command):
    with patch.object(agent, "_call_llm") as model:
        result = agent.handle(command)
    assert result.action_type is None
    model.assert_not_called()


def test_reviewed_simulation_cannot_become_live(db):
    aid = gate.request_approval("send_email", {"to_email": "person@example.org", "subject": "Hello", "body": "Draft"}, db)
    digest = db.execute("SELECT payload_hash FROM approvals WHERE id=?", (aid,)).fetchone()[0]
    gate.approve(aid, db, digest)
    settings = gate.get_settings().model_copy(update={"action_execution_mode": "live"})
    with patch.object(gate, "get_settings", return_value=settings), patch.object(gate, "_dispatch_action") as dispatch:
        with pytest.raises(SecurityPolicyViolationError, match="mode changed"):
            gate.execute_approved(aid, db)
    dispatch.assert_not_called()


def test_kill_switch_after_review_prevents_claim(db):
    aid = gate.request_approval("send_email", {"to_email": "person@example.org", "subject": "Hello", "body": "Draft"}, db)
    digest = db.execute("SELECT payload_hash FROM approvals WHERE id=?", (aid,)).fetchone()[0]
    gate.approve(aid, db, digest)
    with db:
        db.execute("UPDATE system_flags SET value='true' WHERE key='kill_switch'")
    with pytest.raises(KillSwitchActiveError):
        gate.execute_approved(aid, db)
    assert db.execute("SELECT count(*) FROM execution_attempts").fetchone()[0] == 0


def test_old_status_constraint_migrates_and_failed_migration_rolls_back():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    old = SCHEMA_SQL.replace(", 'simulated', 'submitted', 'confirmed', 'failed', 'outcome_unknown'", "")
    conn.executescript(old)
    conn.execute("INSERT INTO approvals(id,action_type,payload_json,status) VALUES('old','send_email','{}','pending')")
    conn.commit()
    conn.set_authorizer(lambda action, name, *args: sqlite3.SQLITE_DENY
                        if action == sqlite3.SQLITE_DROP_TABLE and name == "approvals" else sqlite3.SQLITE_OK)
    with pytest.raises(sqlite3.DatabaseError):
        run_migrations(conn)
    conn.set_authorizer(None)
    assert conn.execute("SELECT status FROM approvals WHERE id='old'").fetchone()[0] == "pending"
    assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='approvals_next'").fetchone()
    run_migrations(conn)
    run_migrations(conn)
    with conn:
        conn.execute("UPDATE approvals SET status='simulated' WHERE id='old'")
    assert not conn.execute("PRAGMA foreign_key_check").fetchall()
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    conn.close()


def test_mode_tampering_before_decision_invalidates_review(db):
    aid = gate.request_approval("send_email", {"to_email": "person@example.org", "subject": "Hello", "body": "Draft"}, db)
    digest = db.execute("SELECT payload_hash FROM approvals WHERE id=?", (aid,)).fetchone()[0]
    with db:
        db.execute("UPDATE approvals SET execution_mode='live' WHERE id=?", (aid,))
    from orchestrator_core.exceptions import ApprovalTamperedError
    with pytest.raises(ApprovalTamperedError):
        gate.approve(aid, db, digest)
