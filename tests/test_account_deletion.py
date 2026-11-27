import pytest
from orchestrator_core.core.identity import create_user, login, principal
from orchestrator_core.core.ownership import OWNED_TABLES
from orchestrator_core.core.policy import execution_scope
from orchestrator_core.core.account_data import remove_account, AccountRemovalError
from orchestrator_core.memory.semantic import remember
from orchestrator_core.memory.vector_write import synchronize_item
from orchestrator_core.jobs.service import JobService


class Collection:
    def __init__(self):
        self.items = {}
        self.fail = False
    def upsert(self, ids, documents, metadatas):
        for key, text, meta in zip(ids, documents, metadatas):
            self.items[key] = (text, meta)
    def delete(self, ids=None, where=None):
        if self.fail:
            raise RuntimeError('private backend details')
        for key in list(self.items):
            if (ids is not None and key in ids) or (where and all(self.items[key][1].get(k) == v for k, v in where.items())):
                del self.items[key]
    def get(self, ids=None, where=None, **kwargs):
        return {'ids': [key for key, (_, meta) in self.items.items() if (ids is None or key in ids) and (not where or all(meta.get(k) == v for k,v in where.items()))]}


class Vectors:
    def __init__(self):
        self.collections = {}
    def get_or_create_collection(self, name):
        return self.collections.setdefault(name, Collection())


def accounts(db):
    alice = create_user(db, 'alice', 'fixture-password-123')['id']
    bob = create_user(db, 'bob', 'fixture-password-123', 'administrator')['id']
    return alice, bob


def test_account_removal_purges_owned_rows_vectors_and_sessions(db):
    alice, bob = accounts(db)
    vectors = Vectors()
    token = login(db, 'alice', 'fixture-password-123', 'fixture')
    items = []
    for owner in (alice, bob):
        with execution_scope('orchestrator', owner=owner):
            JobService.create_job('general_chat', 'Private work', db, owner=owner)
            items.append(remember('Private memory', db=db, owner=owner, pending_review=False, chroma_client=vectors))
    remove_account(db, alice, 'fixture-password-123', vectors)
    assert principal(db, token) is None
    assert db.execute('SELECT 1 FROM users WHERE id=?', (alice,)).fetchone() is None
    for table in OWNED_TABLES:
        assert db.execute(f'SELECT COUNT(*) FROM {table} WHERE user_id=?', (alice,)).fetchone()[0] == 0
    collection = vectors.collections['orchestrator_memory']
    assert items[0].id not in collection.items and items[1].id in collection.items
    assert db.execute('SELECT COUNT(*) FROM memory_items WHERE user_id=?', (bob,)).fetchone()[0] == 1
    # A writer holding a stale snapshot cannot resurrect the removed row.
    assert not synchronize_item(db, items[0].id, alice, collection=collection)
    assert items[0].id not in collection.items


def test_vector_failure_preserves_account_and_marks_retryable_memory(db):
    alice, _ = accounts(db)
    vectors = Vectors()
    item = remember('Keep until deletion completes', db=db, owner=alice, pending_review=False, chroma_client=vectors)
    vectors.collections['orchestrator_memory'].fail = True
    with pytest.raises(AccountRemovalError, match='remains available') as error:
        remove_account(db, alice, 'fixture-password-123', vectors)
    assert 'private backend details' not in str(error.value)
    assert db.execute('SELECT 1 FROM users WHERE id=?', (alice,)).fetchone()
    assert db.execute('SELECT vector_synced_at FROM memory_items WHERE id=?', (item.id,)).fetchone()[0] is None


def test_deletion_requires_password_and_preserves_last_admin(db):
    alice, bob = accounts(db)
    with pytest.raises(AccountRemovalError, match='current password'):
        remove_account(db, alice, 'wrong', Vectors())
    with pytest.raises(AccountRemovalError, match='another active administrator'):
        remove_account(db, bob, 'fixture-password-123', Vectors())
    assert db.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 2


def test_running_work_blocks_account_removal(db):
    alice, _ = accounts(db)
    job = JobService.create_job('general_chat', 'Running work', db, owner=alice)
    JobService.claim_job('fixture-worker', db, job.id)
    with pytest.raises(AccountRemovalError, match='running work'):
        remove_account(db, alice, 'fixture-password-123', Vectors())


def test_deletion_route_requires_csrf_confirmation_and_revokes_session(db, monkeypatch):
    from fastapi.testclient import TestClient
    from orchestrator_core.main import app
    from orchestrator_core.storage.db import get_db_connection
    alice, _ = accounts(db)
    vectors = Vectors()
    monkeypatch.setattr('orchestrator_core.storage.chroma_client.get_chroma_client', lambda: vectors)
    app.dependency_overrides[get_db_connection] = lambda: db
    try:
        client = TestClient(app)
        response = client.post('/auth/login', json={'username': 'alice', 'password': 'fixture-password-123'})
        assert response.status_code == 200
        payload = {'password': 'fixture-password-123', 'confirmation': 'DELETE MY ACCOUNT'}
        assert client.post('/account/delete', json=payload).status_code == 403
        headers = {'x-csrf-token': response.json()['csrf_token']}
        assert client.post('/account/delete', json={**payload, 'confirmation': 'delete'}, headers=headers).status_code == 400
        assert db.execute('SELECT 1 FROM users WHERE id=?', (alice,)).fetchone()
        result = client.post('/account/delete', json=payload, headers=headers)
        assert result.status_code == 200 and result.json() == {'deleted': True}
        assert result.headers['cache-control'] == 'no-store'
        assert client.get('/account').status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_retry_targets_episode_collection(db):
    alice, _ = accounts(db)
    vectors = Vectors()
    db.execute("INSERT INTO memory_items (id,kind,value,pending_review,user_id) VALUES ('episode','episode_summary','Summary',0,?)", (alice,))
    db.commit()
    assert synchronize_item(db, 'episode', alice, client=vectors)
    assert 'episode' in vectors.collections['orchestrator_episodes'].items
    assert 'orchestrator_memory' not in vectors.collections
