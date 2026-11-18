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


@pytest.mark.parametrize('other_role', ['operator', 'administrator'])
def test_memory_routes_reject_foreign_ids_and_sources(db, other_role, monkeypatch):
    monkeypatch.setattr('orchestrator_core.memory.semantic._sync_to_chroma', lambda *a, **k: None)
    create_user(db, 'alice', 'fixture-password-123')
    create_user(db, 'other', 'fixture-password-123', other_role)
    app.dependency_overrides[get_db_connection] = lambda: db
    try:
        alice, other = TestClient(app), TestClient(app)
        headers = {}
        for name, client in [('alice', alice), ('other', other)]:
            csrf = client.post('/auth/login', json={'username': name, 'password': 'fixture-password-123'}).json()['csrf_token']
            headers[name] = {'x-csrf-token': csrf}
        cid = alice.post('/conversations', json={'title': 'Private'}, headers=headers['alice']).json()['id']
        response = alice.post('/memory', json={'value': 'ALICE_SECRET', 'source_session_id': cid}, headers=headers['alice'])
        assert response.status_code == 201
        mid = response.json()['id']
        assert other.get('/memory').json() == []
        assert other.get('/memory/' + mid).status_code == 404
        assert other.patch('/memory/' + mid, json={'value': 'overwritten'}, headers=headers['other']).status_code == 404
        assert other.post('/memory/' + mid + '/confirm', headers=headers['other']).status_code == 404
        assert other.delete('/memory/' + mid, headers=headers['other']).status_code == 404
        assert other.post('/memory/summarize/' + cid, headers=headers['other']).status_code == 404
        assert other.post('/memory', json={'value': 'fake source', 'source_session_id': cid}, headers=headers['other']).status_code == 400
        assert alice.get('/memory/' + mid).json()['value'] == 'ALICE_SECRET'
    finally:
        app.dependency_overrides.clear()


def test_retrieval_rechecks_owner_even_when_vector_index_returns_foreign_ids(db, monkeypatch):
    from orchestrator_core.memory.retrieval import get_context_slice
    alice = create_user(db, 'alice', 'fixture-password-123')['id']
    bob = create_user(db, 'bob', 'fixture-password-123')['id']
    with db:
        db.execute("INSERT INTO memory_items(id,kind,value,pending_review,user_id) VALUES ('private-memory','fact','ALICE_SECRET',0,?)", (alice,))
        db.execute("INSERT INTO memory_items(id,kind,value,pending_review,user_id) VALUES ('own-memory','fact','BOB_FACT',0,?)", (bob,))
    class PoisonedIndex:
        def query(self, **kwargs):
            assert kwargs['where'] == {'user_id': bob}
            return {'ids': [['private-memory']], 'documents': [['ALICE_SECRET']]}
    monkeypatch.setattr('orchestrator_core.memory.retrieval.get_agent_collection', lambda *a, **k: PoisonedIndex())
    context = get_context_slice('facts', db, owner=bob)
    assert 'BOB_FACT' in context
    assert 'ALICE_SECRET' not in context


@pytest.mark.parametrize('other_role', ['operator', 'administrator'])
def test_jobs_are_private_and_cannot_attach_to_foreign_sources(db, other_role, monkeypatch):
    from orchestrator_core.jobs.events import JobEventHub
    create_user(db, 'alice', 'fixture-password-123')
    create_user(db, 'other', 'fixture-password-123', other_role)
    app.dependency_overrides[get_db_connection] = lambda: db
    try:
        clients = {name: TestClient(app) for name in ('alice', 'other')}
        headers = {}
        for name, client in clients.items():
            token = client.post('/auth/login', json={'username': name, 'password': 'fixture-password-123'}).json()['csrf_token']
            headers[name] = {'x-csrf-token': token}
        alice, other = clients.values()
        response = alice.post('/jobs', json={'agent': 'general_chat', 'goal': 'ALICE_PRIVATE_JOB'}, headers=headers['alice'])
        assert response.status_code == 201
        jid = response.json()['id']
        owner = response.json()['user_id']
        assert other.get('/jobs').json()['total'] == 0
        for suffix in ('', '/steps'):
            assert other.get('/jobs/' + jid + suffix).status_code == 404
        assert other.post('/jobs/' + jid + '/cancel', headers=headers['other']).status_code == 404
        assert other.post('/jobs/' + jid + '/answer', json={'answer': 'intrusion'}, headers=headers['other']).status_code == 404
        assert other.post('/jobs', json={'agent': 'general_chat', 'goal': 'child', 'parent_job_id': jid}, headers=headers['other']).status_code == 404
        assert alice.get('/jobs/' + jid).status_code == 200
        class BorrowedConnection:
            def execute(self, *args):
                return db.execute(*args)
            def close(self):
                pass
        monkeypatch.setattr('orchestrator_core.storage.db.get_db', lambda: BorrowedConnection())
        hub = JobEventHub()
        assert any(jid in row['data_json'] for row in hub.read(0, owner=owner)[1])
        other_id = db.execute("SELECT id FROM users WHERE username='other'").fetchone()['id']
        assert hub.read(0, owner=other_id)[1] == []
        assert hub.read(0)[1] == []
    finally:
        app.dependency_overrides.clear()


def test_operational_task_creation_cannot_bypass_policy(db, monkeypatch):
    from orchestrator_core.routes.dispatch import _handle_operational_command
    from orchestrator_core.jobs.service import JobService
    def rejected(**kwargs):
        raise ValueError('admission rejected')
    monkeypatch.setattr(JobService, 'create_job', rejected)
    with pytest.raises(ValueError, match='admission rejected'):
        _handle_operational_command('add task: denied', db, 'session')
    assert db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0] == 0


@pytest.mark.parametrize('other_role', ['operator', 'administrator'])
def test_schedules_keep_their_owner_when_triggered(db, other_role):
    create_user(db, 'alice', 'fixture-password-123')
    create_user(db, 'other', 'fixture-password-123', other_role)
    app.dependency_overrides[get_db_connection] = lambda: db
    try:
        alice, other = TestClient(app), TestClient(app)
        headers = {}
        for name, client in [('alice', alice), ('other', other)]:
            token = client.post('/auth/login', json={'username': name, 'password': 'fixture-password-123'}).json()['csrf_token']
            headers[name] = {'x-csrf-token': token}
        response = alice.post('/schedules', json={'name': 'Private', 'agent': 'general_chat', 'goal': 'Private goal'}, headers=headers['alice'])
        assert response.status_code == 201
        sid = response.json()['id']
        assert other.get('/schedules').json() == []
        assert other.get('/schedules/' + sid).status_code == 404
        assert other.patch('/schedules/' + sid, json={'goal': 'changed'}, headers=headers['other']).status_code == 404
        assert other.delete('/schedules/' + sid, headers=headers['other']).status_code == 404
        assert other.post('/schedules/' + sid + '/run', headers=headers['other']).status_code == 404
        triggered = alice.post('/schedules/' + sid + '/run', headers=headers['alice'])
        assert triggered.status_code == 200
        jid = triggered.json()['job_id']
        assert alice.get('/jobs/' + jid).status_code == 200
        assert other.get('/jobs/' + jid).status_code == 404
    finally:
        app.dependency_overrides.clear()
