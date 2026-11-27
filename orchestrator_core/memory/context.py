"""One bounded source of recent dialogue and reviewed, attributed memory."""
def clip(text, budget):
    return text.encode('utf-8')[:max(0,budget)].decode('utf-8', errors='ignore')


def build_context(db, conversation_id, query='', budget=6000, owner=None):
    # UTF-8 bytes are a conservative token allowance, including non-English text.
    history_budget = budget * 2 // 3
    rows = db.execute("SELECT id,role,content FROM messages WHERE conversation_id=? AND COALESCE(user_id,'')=? ORDER BY created_at DESC,id DESC LIMIT 20",
                      (conversation_id or '', owner or '')).fetchall()
    recent = []
    remaining = history_budget
    for row in rows:
        text = clip(f"{row['role']}: {row['content']}\n", remaining)
        recent.append(text)
        remaining -= len(text.encode('utf-8'))
    # An extractive summary is labelled as such; it does not invent facts.
    if remaining > 100 and len(rows) == 20:
        older = db.execute("SELECT content FROM messages WHERE conversation_id=? AND COALESCE(user_id,'')=? ORDER BY created_at DESC,id DESC LIMIT 5 OFFSET 20", (conversation_id, owner or '')).fetchall()
        summary = clip('Earlier excerpts (not instructions): '+ ' | '.join(r['content'][:120] for r in reversed(older))+'\n', remaining)
        recent.append(summary)
    history = ''.join(reversed(recent))
    memories = []
    remaining = budget-len(history.encode('utf-8'))
    for row in db.execute("SELECT id,value,source_session_id,source_message_id FROM memory_items WHERE pending_review=0 AND deleted=0 AND COALESCE(user_id,'')=? ORDER BY updated_at DESC,id DESC LIMIT 20", (owner or '',)).fetchall():
        text = f"[Reviewed memory {row['id']}; session={row['source_session_id']}; message={row['source_message_id']}] {row['value']}\n"
        text = clip(text, remaining)
        memories.append(text)
        remaining -= len(text.encode('utf-8'))
        if remaining <= 0:
            break
    return {'conversation_history_text': history, 'memory_context': ''.join(memories)}


def synchronize_vectors(db, collection=None):
    from orchestrator_core.core.provider import bounded_call
    from orchestrator_core.memory.vector_write import synchronize_item
    rows = db.execute('SELECT * FROM memory_items WHERE vector_synced_at IS NULL OR vector_synced_at<>updated_at ORDER BY updated_at LIMIT 10').fetchall()
    pg = getattr(db, 'dialect', None) == 'postgresql'
    source = db.raw.info.dsn if pg else db.execute('PRAGMA database_list').fetchone()[2]
    completed = 0
    for row in rows:
        def sync(row=dict(row)):
            if not source:  # Isolated in-memory development/test database.
                return synchronize_item(db, row['id'], row['user_id'], collection=collection)
            if pg:
                from orchestrator_core.storage.postgres import connect
                target = connect(source, pooled=False)
            else:
                from orchestrator_core.storage.db import get_db
                target = get_db(source)
            try:
                return synchronize_item(target, row['id'], row['user_id'], collection=collection)
            finally:
                target.close()
        try:
            # An interrupted writer keeps its own connection and deletion lock;
            # it cannot later resurrect a row deleted by a successful removal.
            changed = bounded_call(sync, timeout=10) if source else sync()
            completed += int(bool(changed))
        except Exception:
            continue
    return completed
