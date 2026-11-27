"""Account removal with password confirmation and serialized vector cleanup."""
from argon2.exceptions import VerificationError, InvalidHashError
from orchestrator_core.core.identity import hasher, digest
from orchestrator_core.core.ownership import OWNED_TABLES
from orchestrator_core.storage.transactions import transaction


class AccountRemovalError(ValueError):
    pass


def remove_account(db, owner, password, client=None):
    user = db.execute('SELECT * FROM users WHERE id=? AND active=1', (owner,)).fetchone()
    try:
        valid = user and hasher.verify(user['password_hash'], password)
    except (VerificationError, InvalidHashError):
        valid = False
    if not valid:
        raise AccountRemovalError('Confirm your current password before deleting your account')
    purge_started = False
    try:
        with transaction(db):
            suffix = ' FOR UPDATE' if getattr(db, 'dialect', None) == 'postgresql' else ''
            current = db.execute('SELECT * FROM users WHERE id=? AND active=1' + suffix, (owner,)).fetchone()
            if not current or current['version'] != user['version']:
                raise AccountRemovalError('Your account changed; sign in and try again')
            if current['role'] == 'administrator' and db.execute("SELECT COUNT(*) FROM users WHERE role='administrator' AND active=1").fetchone()[0] <= 1:
                raise AccountRemovalError('Create another active administrator before deleting this account')
            if db.execute("SELECT 1 FROM jobs WHERE user_id=? AND status='running' LIMIT 1", (owner,)).fetchone() or db.execute("SELECT 1 FROM approvals WHERE user_id=? AND status='executing' LIMIT 1", (owner,)).fetchone():
                raise AccountRemovalError('Wait for running work and in-flight actions to finish before deleting your account')
            from orchestrator_core.storage.chroma_client import get_chroma_client, get_agent_collection, SUPPORTED_AGENTS
            vector_client = client or get_chroma_client()
            memory_ids = [row[0] for row in db.execute('SELECT id FROM memory_items WHERE user_id=?', (owner,)).fetchall()]
            purge_started = True
            for name in sorted(SUPPORTED_AGENTS):
                collection = get_agent_collection(name, client=vector_client)
                collection.delete(where={'user_id': owner})
                # Older memory vectors may predate owner metadata.
                if name in ('memory', 'episodes'):
                    for offset in range(0, len(memory_ids), 500):
                        collection.delete(ids=memory_ids[offset:offset+500])
                if collection.get(where={'user_id': owner}, limit=1, include=[])['ids']:
                    raise AccountRemovalError('Vector cleanup is incomplete; retry deletion')
                if name in ('memory', 'episodes'):
                    for offset in range(0, len(memory_ids), 500):
                        if collection.get(ids=memory_ids[offset:offset+500], include=[])['ids']:
                            raise AccountRemovalError('Vector cleanup is incomplete; retry deletion')
            # Audit payloads can contain personal proposals. Remove records tied
            # to owned entities before deleting their primary rows.
            for table in OWNED_TABLES:
                key = 'run_id' if table in ('pipeline_runs', 'pipeline_steps') else 'eval_id' if table == 'router_eval_runs' else 'id'
                if table in ('schedule_occurrences', 'job_events'):
                    continue
                db.execute(f'DELETE FROM audit_log WHERE entity_id IN (SELECT CAST({key} AS TEXT) FROM {table} WHERE user_id=?)', (owner,))
            db.execute('DELETE FROM audit_log WHERE actor=? OR entity_id=?', (owner, owner))
            db.execute('UPDATE jobs SET parent_job_id=NULL WHERE user_id=?', (owner,))
            db.execute('UPDATE approvals SET supersedes_id=NULL WHERE user_id=?', (owner,))
            order = ('memory_items','job_dependencies','job_steps','job_events','execution_attempts','pipeline_steps','schedule_occurrences','provider_usage','router_eval_runs','jobs','approvals','pipeline_runs','schedules','messages','conversations','connections','oauth_states','account_tokens','sessions')
            for table in order:
                db.execute(f'DELETE FROM {table} WHERE user_id=?', (owner,))
            for name in {current['username'], current['email']}:
                if name:
                    for prefix in ('account:', 'register:account:', 'reset-request:account:'):
                        db.execute('DELETE FROM login_limits WHERE key=?', (prefix + digest(name),))
            db.execute('DELETE FROM users WHERE id=?', (owner,))
    except AccountRemovalError:
        if purge_started:
            with db:
                db.execute('UPDATE memory_items SET vector_synced_at=NULL WHERE user_id=?', (owner,))
        raise
    except Exception:
        # SQL remains intact after failure; restore any partially purged vectors.
        with db:
            db.execute('UPDATE memory_items SET vector_synced_at=NULL WHERE user_id=?', (owner,))
        raise AccountRemovalError('Account deletion could not finish. Your account remains available; retry when storage is healthy') from None
