import pytest
from fastapi.testclient import TestClient
from orchestrator_core.core.identity import create_user
from orchestrator_core.main import app
from orchestrator_core.storage.db import get_db_connection


@pytest.mark.parametrize('other_role', ['operator', 'administrator'])
def test_conversations_are_private_even_from_administrators(db, other_role, monkeypatch):
    class BorrowedConnection:
        def execute(self, *args):
            return db.execute(*args)
        def close(self):
            pass
    monkeypatch.setattr('orchestrator_core.routes.dispatch.get_db', lambda: BorrowedConnection())
    create_user(db, 'alice', 'fixture-password-123')
    create_user(db, 'other', 'fixture-password-123', other_role)
    app.dependency_overrides[get_db_connection] = lambda: db
    try:
        alice = TestClient(app)
        csrf = alice.post('/auth/login', json={'username': 'alice', 'password': 'fixture-password-123'}).json()['csrf_token']
        response = alice.post('/conversations', json={'title': 'Alice private'}, headers={'x-csrf-token': csrf})
        assert response.status_code == 201
        cid = response.json()['id']
        other = TestClient(app)
        other_csrf = other.post('/auth/login', json={'username': 'other', 'password': 'fixture-password-123'}).json()['csrf_token']
        assert other.get('/conversations').json() == []
        assert other.get('/conversations/' + cid).status_code == 404
        assert other.get('/conversations/' + cid + '/messages').status_code == 404
        assert other.delete('/conversations/' + cid, headers={'x-csrf-token': other_csrf}).status_code == 404
        assert other.post('/dispatch', json={'command': 'hello', 'conversation_id': cid}, headers={'x-csrf-token': other_csrf}).status_code == 404
        assert other.post('/dispatch/stream', json={'command': 'hello', 'conversation_id': cid}, headers={'x-csrf-token': other_csrf}).status_code == 404
        assert alice.get('/conversations/' + cid).status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_context_never_reads_another_owners_messages_or_memory(db):
    from orchestrator_core.memory.context import build_context
    alice = create_user(db, 'alice', 'fixture-password-123')['id']
    bob = create_user(db, 'bob', 'fixture-password-123')['id']
    with db:
        db.execute("INSERT INTO conversations(id,title,user_id) VALUES ('private','Private',?)", (alice,))
        db.execute("INSERT INTO messages(id,conversation_id,role,content,user_id) VALUES ('m','private','user','ALICE_SECRET',?)", (alice,))
        db.execute("INSERT INTO memory_items(id,kind,value,pending_review,user_id) VALUES ('memory','fact','ALICE_MEMORY',0,?)", (alice,))
    assert 'ALICE_SECRET' in build_context(db, 'private', owner=alice)['conversation_history_text']
    assert 'ALICE_MEMORY' in build_context(db, 'private', owner=alice)['memory_context']
    result = build_context(db, 'private', owner=bob)
    assert result == {'conversation_history_text': '', 'memory_context': ''}
