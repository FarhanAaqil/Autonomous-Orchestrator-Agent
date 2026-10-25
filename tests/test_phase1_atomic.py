import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

import pytest
from orchestrator_core.core import approval_gate as gate
from orchestrator_core.exceptions import ApprovalGateError
from orchestrator_core.storage.db import get_db, run_migrations

EMAIL = {"to_email": "person@example.org", "subject": "Review", "body": "Draft"}


def seed(db):
    aid = gate.request_approval("send_email", EMAIL, db)
    digest = db.execute("SELECT payload_hash FROM approvals WHERE id=?", (aid,)).fetchone()[0]
    return aid, digest


def race(path, operations):
    barrier = Barrier(len(operations))
    def run(operation):
        conn = get_db(str(path))
        try:
            barrier.wait(timeout=5)
            operation(conn)
            return "won"
        except ApprovalGateError:
            return "lost"
        finally:
            conn.close()
    with ThreadPoolExecutor(max_workers=len(operations)) as pool:
        return list(pool.map(run, operations))


def test_approve_reject_race_has_one_decision_and_audit(tmp_path):
    path = tmp_path / "race.db"
    db = get_db(str(path))
    aid, digest = seed(db)
    results = race(path, [lambda c: gate.approve(aid, c, digest), lambda c: gate.reject(aid, c)])
    assert sorted(results) == ["lost", "won"]
    events = db.execute("SELECT event FROM audit_log WHERE entity_id=?", (aid,)).fetchall()
    assert sum(r[0] in ("approval_granted", "approval_rejected") for r in events) == 1
    db.close()


def test_execute_edit_race_cannot_supersede_executed(tmp_path):
    path = tmp_path / "race.db"
    db = get_db(str(path))
    aid, digest = seed(db)
    gate.approve(aid, db, digest)
    with patch.object(gate, "_dispatch_action"):
        results = race(path, [lambda c: gate.execute_approved(aid, c),
                             lambda c: gate.edit_and_supersede(aid, {**EMAIL, "body": "Changed"}, c)])
    assert sorted(results) == ["lost", "won"]
    state = db.execute("SELECT status FROM approvals WHERE id=?", (aid,)).fetchone()[0]
    replacements = db.execute("SELECT count(*) FROM approvals WHERE supersedes_id=?", (aid,)).fetchone()[0]
    assert (state, replacements) in (("executed", 0), ("superseded", 1))
    db.close()


def test_audit_failure_rolls_back_decision_and_replacement(db):
    aid, digest = seed(db)
    with patch.object(gate, "log_audit", side_effect=sqlite3.OperationalError("injected")):
        with pytest.raises(sqlite3.OperationalError):
            gate.approve(aid, db, digest)
        with pytest.raises(sqlite3.OperationalError):
            gate.edit_and_supersede(aid, {**EMAIL, "body": "Changed"}, db)
    assert db.execute("SELECT status FROM approvals WHERE id=?", (aid,)).fetchone()[0] == "pending"
    assert db.execute("SELECT count(*) FROM approvals").fetchone()[0] == 1


def test_existing_database_migrates_without_losing_proposals(db):
    aid, _ = seed(db)
    with db:
        for column in ("version", "source_agent", "session_id"):
            db.execute(f"ALTER TABLE approvals DROP COLUMN {column}")
    run_migrations(db)
    run_migrations(db)
    row = db.execute("SELECT * FROM approvals WHERE id=?", (aid,)).fetchone()
    assert row["version"] == 0 and row["status"] == "pending"
    assert not db.execute("PRAGMA foreign_key_check").fetchall()
