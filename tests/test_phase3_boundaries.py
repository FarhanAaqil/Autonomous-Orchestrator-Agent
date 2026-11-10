from fastapi.testclient import TestClient
from orchestrator_core.core import identity
from orchestrator_core.storage.db import get_db_connection
from orchestrator_core.main import app


def test_accounts_are_admin_only_and_never_include_passwords(db):
    identity.create_user(db, 'admin', 'fixture-only-password-123', 'administrator')
    identity.create_user(db, 'reader', 'fixture-only-password-123', 'viewer')
    app.dependency_overrides[get_db_connection] = lambda: db
    try:
        client = TestClient(app)
        client.post('/auth/login', json={'username': 'reader', 'password': 'fixture-only-password-123'})
        assert client.get('/auth/users').status_code == 403
        client.post('/auth/login', json={'username': 'admin', 'password': 'fixture-only-password-123'})
        result = client.get('/auth/users')
        assert result.status_code == 200
        assert all(set(row) == {'id', 'username', 'role', 'active'} for row in result.json())
    finally:
        app.dependency_overrides.clear()


def test_chat_cannot_change_administrator_controls(db):
    import pytest
    from orchestrator_core.routes.dispatch import _handle_operational_command
    from orchestrator_core.exceptions import SecurityPolicyViolationError
    before = db.execute("SELECT value FROM system_flags WHERE key='kill_switch'").fetchone()[0]
    with pytest.raises(SecurityPolicyViolationError):
        _handle_operational_command('kill switch on', db, 'fixture')
    assert db.execute("SELECT value FROM system_flags WHERE key='kill_switch'").fetchone()[0] == before


def test_recent_history_is_chronological_and_has_older_pages(db):
    from orchestrator_core.routes.conversations import get_conversation_messages
    with db:
        db.execute("INSERT INTO conversations(id,title) VALUES ('history','History')")
        for i in range(5):
            db.execute("INSERT INTO messages(id,conversation_id,role,content,created_at) VALUES (?,'history','user',?,?)",
                       (str(i), str(i), f'2026-01-01T00:00:0{i}+00:00'))
    recent = get_conversation_messages('history', limit=2, offset=0, db=db)
    older = get_conversation_messages('history', limit=2, offset=2, db=db)
    assert [row.content for row in recent] == ['3', '4']
    assert [row.content for row in older] == ['1', '2']


def test_only_compiled_assets_are_exposed():
    client = TestClient(app)
    for path in ['/static/package.json', '/static/src/App.tsx', '/static/node_modules/react/package.json']:
        assert client.get(path).status_code == 404
    health = client.get('/health').json()
    assert health['service'] == 'toji-orchestrator'
