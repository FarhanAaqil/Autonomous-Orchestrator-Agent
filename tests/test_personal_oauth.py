import json
from urllib.parse import parse_qs, urlsplit
import pytest
from cryptography.fernet import Fernet
from orchestrator_core.core.identity import create_user
from orchestrator_core.core.connections import ConnectionUnavailable, load_connection
from orchestrator_core.core import oauth


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv('CONNECTION_KEYS', json.dumps({'one': Fernet.generate_key().decode()}))
    monkeypatch.setenv('CONNECTION_ACTIVE_KEY', 'one')
    monkeypatch.setenv('PUBLIC_BASE_URL', 'https://fixture.example')
    monkeypatch.setenv('GITHUB_OAUTH_CLIENT_ID', 'fixture-client')
    monkeypatch.setenv('GITHUB_OAUTH_CLIENT_SECRET', 'fixture-secret')


def test_oauth_state_is_private_session_bound_and_single_use(db, configured, monkeypatch):
    alice = create_user(db, 'alice', 'fixture-password-123')['id']
    bob = create_user(db, 'bob', 'fixture-password-123')['id']
    url = oauth.begin(db, alice, 'github', 'alice-session')
    params = parse_qs(urlsplit(url).query)
    state = params['state'][0]
    assert params['code_challenge_method'] == ['S256']
    saved = dict(db.execute('SELECT * FROM oauth_states').fetchone())
    assert state not in json.dumps(saved)
    class Response:
        status_code = 200
        def __init__(self, value):
            self.value = value
        def json(self):
            return self.value
    calls = []
    def exchange(url, **kwargs):
        calls.append(kwargs)
        assert kwargs['data']['code_verifier'] not in saved['verifier']
        return Response({'access_token': 'alice-provider-secret', 'scope': 'repo,read:user'})
    monkeypatch.setattr(oauth.requests, 'post', exchange)
    monkeypatch.setattr(oauth.requests, 'get', lambda *a, **k: Response({'login': 'alice-github'}))
    for owner, session in [(bob, 'alice-session'), (alice, 'other-session')]:
        with pytest.raises(ConnectionUnavailable):
            oauth.complete(db, owner, 'github', session, state, 'code')
    assert not calls
    oauth.complete(db, alice, 'github', 'alice-session', state, 'code')
    assert load_connection(db, alice, 'github')['login'] == 'alice-github'
    with pytest.raises(ConnectionUnavailable):
        load_connection(db, bob, 'github')
    with pytest.raises(ConnectionUnavailable):
        oauth.complete(db, alice, 'github', 'alice-session', state, 'code')
    assert len(calls) == 1


def test_gmail_beta_fails_closed(db, configured, monkeypatch):
    owner = create_user(db, 'fixture@example.com', 'fixture-password-123')['id']
    monkeypatch.setenv('GOOGLE_OAUTH_CLIENT_ID', 'fixture')
    monkeypatch.setenv('GOOGLE_OAUTH_CLIENT_SECRET', 'fixture')
    monkeypatch.delenv('GMAIL_BETA_EMAILS', raising=False)
    with pytest.raises(ConnectionUnavailable, match='private beta'):
        oauth.begin(db, owner, 'gmail_send', 'session')
    assert db.execute('SELECT COUNT(*) FROM oauth_states').fetchone()[0] == 0


def test_read_tools_never_use_operator_or_another_accounts_secret(db, configured, monkeypatch):
    from orchestrator_core.core.connections import store_connection, disconnect
    from orchestrator_core.core.policy import execution_scope
    from orchestrator_core.core.usage import usage_db
    from orchestrator_core.agents.github_agent import _api_get
    from orchestrator_core.agents.email_agent import check_inbox
    alice = create_user(db, 'alice', 'fixture-password-123')['id']
    bob = create_user(db, 'bob', 'fixture-password-123')['id']
    store_connection(db, alice, 'github', {'access_token': 'alice-token'}, [])
    monkeypatch.setenv('GITHUB_TOKEN', 'operator-secret')
    monkeypatch.setenv('EMAIL_ADDRESS', 'operator@example.com')
    monkeypatch.setenv('EMAIL_APP_PASSWORD', 'operator-secret')
    seen = []
    class Response:
        status_code = 200
        def json(self):
            return {'login': 'alice'}
    def get(url, **kwargs):
        seen.append(kwargs['headers']['Authorization'])
        return Response()
    monkeypatch.setattr('orchestrator_core.core.personal_providers.requests.get', get)
    marker = usage_db.set(db)
    try:
        with execution_scope('github_agent', owner=alice):
            assert _api_get('/user')['login'] == 'alice'
        with execution_scope('github_agent', owner=bob):
            with pytest.raises(ConnectionUnavailable):
                _api_get('/user')
            with pytest.raises(ConnectionUnavailable):
                check_inbox()
        disconnect(db, alice, 'github')
        with execution_scope('github_agent', owner=alice):
            with pytest.raises(ConnectionUnavailable):
                _api_get('/user')
    finally:
        usage_db.reset(marker)
    assert seen == ['Bearer alice-token']
