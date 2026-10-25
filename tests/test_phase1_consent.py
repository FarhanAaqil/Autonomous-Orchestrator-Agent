import pytest
from orchestrator_core.core.approval_gate import request_approval, approve, execute_approved
from orchestrator_core.exceptions import ApprovalHashMismatchError, ApprovalExpiredError, SecurityPolicyViolationError, ApprovalSignatureInvalidError
from orchestrator_core.routes.dispatch import _handle_operational_command

EMAIL = {"to_email": "person@example.org", "subject": "Review", "body": "Draft"}


def proposal(db, **kwargs):
    aid = request_approval("send_email", EMAIL, db, **kwargs)
    return aid, db.execute("SELECT payload_hash FROM approvals WHERE id=?", (aid,)).fetchone()[0]


@pytest.mark.parametrize("command", ["yes", "confirm", "send it", "approve", "approve abcd", "reject", "no"])
def test_chat_does_not_choose_a_proposal(db, command):
    aid, _ = proposal(db, session_id="other-chat")
    _handle_operational_command(command, db, 'chat-a')
    assert db.execute("SELECT status FROM approvals WHERE id=?", (aid,)).fetchone()[0] == "pending"


def test_review_requires_hash_and_matching_session(db):
    aid, digest = proposal(db, session_id="chat-a")
    for wrong_hash in (None, "0" * 64):
        with pytest.raises(ApprovalHashMismatchError):
            approve(aid, db, wrong_hash, "chat-a")
    with pytest.raises(SecurityPolicyViolationError):
        approve(aid, db, digest, "chat-b")
    approve(aid, db, digest, "chat-a")
    assert db.execute("SELECT status FROM approvals WHERE id=?", (aid,)).fetchone()[0] == "approved"


def test_expired_review_refused(db):
    aid, digest = proposal(db, expiry_hours=-1)
    with pytest.raises(ApprovalExpiredError):
        approve(aid, db, digest)


def test_expiry_cannot_be_extended_after_consent(db):
    aid, digest = proposal(db)
    approve(aid, db, digest)
    with db:
        db.execute("UPDATE approvals SET expires_at='2099-01-01T00:00:00+00:00' WHERE id=?", (aid,))
    with pytest.raises(ApprovalSignatureInvalidError):
        execute_approved(aid, db)
