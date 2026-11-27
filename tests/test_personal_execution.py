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


PUBLISH_CASES = [
    ('github_create_issue', {'repo': 'owner/repo', 'title': 'Reviewed issue', 'body': 'Details'}, 'github', 'https://api.github.com/repos/owner/repo/issues', 201, {'id': 123}),
    ('github_comment', {'repo': 'owner/repo', 'issue_number': 12, 'body': 'Reviewed comment'}, 'github', 'https://api.github.com/repos/owner/repo/issues/12/comments', 201, {'id': 124}),
    ('publish_devto', {'title': 'Reviewed article', 'content': 'Article body'}, 'devto', 'https://dev.to/api/articles', 201, {'id': 125}),
    ('publish_hashnode', {'title': 'Reviewed article', 'content': 'Article body', 'publication_id': '0123456789abcdef01234567'}, 'hashnode', 'https://gql-beta.hashnode.com', 200, {'data': {'publishPost': {'post': {'id': 'post-id'}}}}),
]


@pytest.mark.parametrize('action,payload,provider,url,status,receipt', PUBLISH_CASES)
def test_publishing_uses_only_reviewed_personal_content(db, monkeypatch, action, payload, provider, url, status, receipt):
    import json
    from cryptography.fernet import Fernet
    from orchestrator_core.core.connections import store_connection
    monkeypatch.setenv('CONNECTION_KEYS', json.dumps({'test': Fernet.generate_key().decode()}))
    monkeypatch.setenv('CONNECTION_ACTIVE_KEY', 'test')
    owner = create_user(db, 'publisher', 'fixture-password-123')['id']
    with db:
        db.execute("UPDATE users SET execution_mode='live' WHERE id=?", (owner,))
    store_connection(db, owner, provider, {'access_token': 'personal-publish-token'}, [])
    marker = execution_owner.set(owner)
    try:
        aid = request_approval(action, payload, db)
    finally:
        execution_owner.reset(marker)
    call = Mock(return_value=Mock(status_code=status, json=Mock(return_value=receipt)))
    monkeypatch.setattr('requests.post', call)
    with pytest.raises(Exception):
        execute_approved(aid, db)
    call.assert_not_called()
    row = db.execute('SELECT * FROM approvals WHERE id=?', (aid,)).fetchone()
    approve(aid, db, row['payload_hash'])
    result = execute_approved(aid, db)
    assert result['outcome'] == 'submitted'
    assert result['receipt']['provider'] == provider
    assert call.call_count == 1
    assert call.call_args.args[0] == url
    kwargs = call.call_args.kwargs
    assert kwargs['allow_redirects'] is False and kwargs['timeout'] == 20
    assert 'personal-publish-token' in str(kwargs['headers'])
    assert 'personal-publish-token' not in str(result)
    if provider == 'github':
        assert kwargs['json']['body'] == payload['body']
    elif provider == 'devto':
        assert kwargs['json']['article'] == {'title': payload['title'], 'body_markdown': payload['content'], 'published': True}
    else:
        assert kwargs['json']['variables']['input']['publicationId'] == payload['publication_id']
    with pytest.raises(Exception):
        execute_approved(aid, db)
    assert call.call_count == 1


@pytest.mark.parametrize('action,payload,provider,url,status,receipt', PUBLISH_CASES)
def test_publishing_simulation_and_uncertain_results_never_retry(monkeypatch, action, payload, provider, url, status, receipt):
    import requests
    call = Mock(side_effect=requests.Timeout('private-provider-secret'))
    monkeypatch.setattr('requests.post', call)
    assert _dispatch_personal(action, payload, 'approval', 'simulation', None)['outcome'] == 'simulated'
    call.assert_not_called()
    result = _dispatch_personal(action, payload, 'approval', 'live', 'fixture-token')
    assert result == {'outcome': 'outcome_unknown', 'error_class': 'UnconfirmedProviderResponse'}
    assert call.call_count == 1


def test_hashnode_destination_is_part_of_consent(db):
    from orchestrator_core.core.action_catalog import normalize_action
    payload = PUBLISH_CASES[-1][1]
    _, canonical, target = normalize_action('publish_hashnode', payload)
    assert target == canonical['publication_id']
    with pytest.raises(SecurityPolicyViolationError):
        normalize_action('publish_hashnode', payload, 'abcdef0123456789abcdef01')


@pytest.mark.parametrize('status,data,outcome', [(403, {}, 'failed'), (500, {}, 'outcome_unknown'), (201, {}, 'outcome_unknown')])
def test_publishing_requires_receipt_and_sanitizes_errors(monkeypatch, status, data, outcome):
    monkeypatch.setattr('requests.post', Mock(return_value=Mock(status_code=status, json=Mock(return_value=data))))
    action, payload, *_ = PUBLISH_CASES[0]
    assert _dispatch_personal(action, payload, 'approval', 'live', 'fixture-token')['outcome'] == outcome


def test_publication_proposal_uses_explicit_destination_without_inventing_one(monkeypatch):
    from orchestrator_core.agents import growth_content_agent as agent
    monkeypatch.setattr(agent, '_call_llm', lambda command: '# Article\nReviewed body')
    missing = agent.handle('Publish on Hashnode')
    assert 'publication_id' not in missing.metadata['approval_payload']
    explicit = agent.handle('Publish on Hashnode publication id: 0123456789abcdef01234567')
    assert explicit.metadata['approval_payload']['publication_id'] == '0123456789abcdef01234567'
    assert 'Farhan' not in agent._SYSTEM_PROMPT
