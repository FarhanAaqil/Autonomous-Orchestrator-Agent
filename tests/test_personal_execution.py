from unittest.mock import Mock
import pytest
from orchestrator_core.core.identity import create_user
from orchestrator_core.core.ownership import execution_owner
from orchestrator_core.core.approval_gate import request_approval, approve, execute_approved, _dispatch_personal
from orchestrator_core.core.connections import ConnectionUnavailable
from orchestrator_core.exceptions import SecurityPolicyViolationError

EMAIL = {'to_email': 'fixture@example.org', 'subject': 'Review', 'body': 'Private draft'}


def proposal(db, owner):
    marker = execution_owner.set(owner)
    try:
        aid = request_approval('send_email', EMAIL, db)
    finally:
        execution_owner.reset(marker)
    row = db.execute('SELECT * FROM approvals WHERE id=?', (aid,)).fetchone()
    approve(aid, db, row['payload_hash'])
    return aid


def test_personal_simulation_cannot_use_operator_transport(db, monkeypatch):
    owner = create_user(db, 'alice', 'fixture-password-123')['id']
    def forbidden(*args, **kwargs):
        raise AssertionError('Operator transport must not run')
    monkeypatch.setattr('orchestrator_core.core.approval_gate._dispatch_action', forbidden)
    result = execute_approved(proposal(db, owner), db)
    assert result['outcome'] == 'simulated'
    assert result['receipt']['external_effect'] is False


def test_mode_change_invalidates_existing_consent(db):
    owner = create_user(db, 'alice', 'fixture-password-123')['id']
    aid = proposal(db, owner)
    with db:
        db.execute("UPDATE users SET execution_mode='live' WHERE id=?", (owner,))
    with pytest.raises(SecurityPolicyViolationError, match='mode changed'):
        execute_approved(aid, db)
    assert db.execute('SELECT COUNT(*) FROM execution_attempts').fetchone()[0] == 0


def test_missing_personal_grant_does_not_claim_an_attempt(db, monkeypatch):
    owner = create_user(db, 'alice@example.org', 'fixture-password-123')['id']
    with db:
        db.execute("UPDATE users SET execution_mode='live' WHERE id=?", (owner,))
    monkeypatch.setenv('GMAIL_BETA_EMAILS', 'alice@example.org')
    aid = proposal(db, owner)
    with pytest.raises(ConnectionUnavailable):
        execute_approved(aid, db)
    assert db.execute('SELECT COUNT(*) FROM execution_attempts').fetchone()[0] == 0
    assert db.execute('SELECT status FROM approvals WHERE id=?', (aid,)).fetchone()[0] == 'approved'


def test_personal_gmail_acceptance_is_not_delivery(monkeypatch):
    response = Mock(status_code=200)
    response.json.return_value = {'id': 'provider-message'}
    call = Mock(return_value=response)
    monkeypatch.setattr('requests.post', call)
    result = _dispatch_personal('send_email', EMAIL, 'approval-one', 'live', 'personal-token')
    assert result['outcome'] == 'submitted'
    assert call.call_args.kwargs['headers']['Authorization'] == 'Bearer personal-token'
    assert call.call_args.kwargs['allow_redirects'] is False
    assert 'personal-token' not in str(result)


def test_personal_gmail_timeout_is_unknown(monkeypatch):
    import requests
    monkeypatch.setattr('requests.post', Mock(side_effect=requests.Timeout('private-token')))
    result = _dispatch_personal('send_email', EMAIL, 'approval-one', 'live', 'personal-token')
    assert result['outcome'] == 'outcome_unknown'
    assert 'private-token' not in str(result)
