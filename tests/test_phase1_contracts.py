import json
import pytest
from orchestrator_core.core.action_catalog import normalize_action, ACTION_CATALOG
from orchestrator_core.core.approval_gate import request_approval, approve
from orchestrator_core.exceptions import SecurityPolicyViolationError


EMAIL = {"to": "person@example.org", "subject": "Review", "body": "A draft"}


@pytest.mark.parametrize("changes,target", [({"recipient": "other@example.org"}, None), ({}, "blocked@example.com"), ({"target": "other@example.org"}, None)])
def test_targets_cannot_disagree(changes, target):
    with pytest.raises(SecurityPolicyViolationError):
        normalize_action("send_email", {**EMAIL, **changes}, target)


def test_unknown_and_header_injection_rejected(db):
    for name, payload in [("nonexistent", EMAIL), ("send_email", {**EMAIL, "subject": "Hello\nBcc: other@example.org"})]:
        with pytest.raises(SecurityPolicyViolationError):
            request_approval(name, payload, db)


def test_canonical_recipient_is_stored(db):
    aid = request_approval("send_email", EMAIL, db)
    row = db.execute("SELECT * FROM approvals WHERE id=?", (aid,)).fetchone()
    assert json.loads(row["payload_json"])["to_email"] == row["target"]
    assert "to" not in json.loads(row["payload_json"])


def test_unavailable_adapter_cannot_be_approved(db):
    aid = request_approval("github_issue", {"repo": "owner/repo", "title": "Issue", "body": "Details"}, db)
    with pytest.raises(SecurityPolicyViolationError):
        approve(aid, db, db.execute("SELECT payload_hash FROM approvals WHERE id=?", (aid,)).fetchone()[0])
    assert all(s.schema and s.agents for s in ACTION_CATALOG.values())
