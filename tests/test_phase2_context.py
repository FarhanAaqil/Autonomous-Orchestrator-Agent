from orchestrator_core.memory.context import build_context, synchronize_vectors


def test_recent_messages_and_reviewed_memory_are_bounded(db):
    db.execute("INSERT INTO conversations (id,title) VALUES ('c','Context')")
    for i in range(30):
        db.execute("INSERT INTO messages (id,conversation_id,role,content,created_at) VALUES (?,'c','user',?,?)", (str(i), f'message-{i}', f'2026-01-01T00:00:{i:02d}'))
    for name, pending, deleted in [('reviewed',0,0),('pending',1,0),('deleted',0,1)]:
        db.execute('INSERT INTO memory_items (id,kind,value,pending_review,deleted) VALUES (?,\'fact\',?,?,?)', (name,name,pending,deleted))
    db.commit()
    context = build_context(db, 'c', budget=2000)
    assert 'message-29' in context['conversation_history_text']
    assert 'reviewed' in context['memory_context']
    assert 'pending' not in context['memory_context'] and 'deleted' not in context['memory_context']
    assert sum(len(v.encode()) for v in context.values()) <= 2000


def test_failed_vector_sync_remains_retryable(db):
    db.execute("INSERT INTO memory_items (id,kind,value,pending_review) VALUES ('m','fact','Reviewed',0)")
    db.commit()
    class Collection:
        def upsert(self, **kwargs):
            raise RuntimeError('offline')
    assert synchronize_vectors(db, Collection()) == 0
    assert db.execute("SELECT vector_synced_at FROM memory_items WHERE id='m'").fetchone()[0] is None
