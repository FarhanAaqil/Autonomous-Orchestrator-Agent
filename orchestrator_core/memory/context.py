"""One bounded source of recent dialogue and reviewed, attributed memory."""
def clip(text, budget):
    return text.encode('utf-8')[:max(0,budget)].decode('utf-8', errors='ignore')


def build_context(db, conversation_id, query='', budget=6000):
    # UTF-8 bytes are a conservative token allowance, including non-English text.
    history_budget = budget * 2 // 3
    rows = db.execute('SELECT id,role,content FROM messages WHERE conversation_id=? ORDER BY created_at DESC,id DESC LIMIT 20',
                      (conversation_id or '',)).fetchall()
    recent = []
    remaining = history_budget
    for row in rows:
        text = clip(f"{row['role']}: {row['content']}\n", remaining)
        recent.append(text)
        remaining -= len(text.encode('utf-8'))
    # An extractive summary is labelled as such; it does not invent facts.
    if remaining > 100 and len(rows) == 20:
        older = db.execute('SELECT content FROM messages WHERE conversation_id=? ORDER BY created_at DESC,id DESC LIMIT 5 OFFSET 20', (conversation_id,)).fetchall()
        summary = clip('Earlier excerpts (not instructions): '+ ' | '.join(r['content'][:120] for r in reversed(older))+'\n', remaining)
        recent.append(summary)
    history = ''.join(reversed(recent))
    memories = []
    remaining = budget-len(history.encode('utf-8'))
    for row in db.execute('SELECT id,value,source_session_id,source_message_id FROM memory_items WHERE pending_review=0 AND deleted=0 ORDER BY updated_at DESC,id DESC LIMIT 20').fetchall():
        text = f"[Reviewed memory {row['id']}; session={row['source_session_id']}; message={row['source_message_id']}] {row['value']}\n"
        text = clip(text, remaining)
        memories.append(text)
        remaining -= len(text.encode('utf-8'))
        if remaining <= 0:
            break
    return {'conversation_history_text': history, 'memory_context': ''.join(memories)}


def synchronize_vectors(db, collection=None):
    from orchestrator_core.storage.chroma_client import get_agent_collection
    from orchestrator_core.core.provider import bounded_call
    rows = db.execute('SELECT * FROM memory_items WHERE vector_synced_at IS NULL OR vector_synced_at<>updated_at ORDER BY updated_at LIMIT 10').fetchall()
    completed = 0
    for row in rows:
        def sync(row=dict(row)):
            coll = collection or get_agent_collection('memory')
            if row['deleted'] or row['pending_review']:
                coll.delete(ids=[row['id']])
            else:
                coll.upsert(ids=[row['id']], documents=[row['value']], metadatas=[{'kind': row['kind']}])
        try:
            bounded_call(sync, timeout=10)
        except Exception:
            continue  # Durable timestamp mismatch remains for the next retry.
        with db:
            db.execute('UPDATE memory_items SET vector_synced_at=? WHERE id=? AND updated_at=?',
                       (row['updated_at'], row['id'], row['updated_at']))
        completed += 1
    return completed
