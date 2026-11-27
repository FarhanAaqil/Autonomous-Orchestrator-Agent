"""Serialize vector writes with account deletion and re-read SQL before writing."""
from orchestrator_core.storage.transactions import transaction
from orchestrator_core.storage.chroma_client import get_agent_collection


def synchronize_item(db, item_id, owner, *, client=None, collection=None, name='memory'):
    with transaction(db):
        if owner is not None and not db.execute('SELECT 1 FROM users WHERE id=? AND active=1', (owner,)).fetchone():
            return False
        row = db.execute("SELECT * FROM memory_items WHERE id=? AND COALESCE(user_id,'')=?", (item_id, owner or '')).fetchone()
        if not row:
            return False
        target_name = 'episodes' if row['kind'] == 'episode_summary' else name
        coll = collection or get_agent_collection(target_name, client=client)
        if row['deleted'] or row['pending_review']:
            coll.delete(ids=[item_id])
        else:
            text = ('Key: ' + row['key'] + '\n' if row['key'] else '') + row['value']
            coll.upsert(ids=[item_id], documents=[text], metadatas=[{'user_id': owner or '', 'id': item_id, 'kind': row['kind'], 'key': row['key'] or '', 'pending_review': '0', 'source_session_id': row['source_session_id'] or ''}])
        db.execute('UPDATE memory_items SET vector_synced_at=? WHERE id=?', (row['updated_at'], item_id))
        return True
