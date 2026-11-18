"""Owner-bound encrypted secrets. No server-credential fallback."""
import json
import os
from cryptography.fernet import Fernet, InvalidToken
from orchestrator_core.core.identity import now
from orchestrator_core.storage.db import log_audit

PROVIDERS = frozenset({'github', 'devto', 'hashnode', 'gmail_read', 'gmail_send', 'groq'})


class ConnectionUnavailable(ValueError):
    pass


def keyring():
    try:
        keys = json.loads(os.environ.get('CONNECTION_KEYS', '{}'))
        active = os.environ.get('CONNECTION_ACTIVE_KEY', '')
        if not isinstance(keys, dict) or active not in keys:
            raise ValueError()
        return active, {name: Fernet(value.encode()) for name, value in keys.items()}
    except (ValueError, TypeError, AttributeError):
        raise ConnectionUnavailable('Provider connections are not configured') from None


def store_connection(db, user_id, provider, secret, scopes):
    if provider not in PROVIDERS or not isinstance(secret, dict) or not secret:
        raise ValueError('Unsupported provider or empty credentials')
    if not db.execute('SELECT 1 FROM users WHERE id=? AND active=1', (user_id,)).fetchone():
        raise ConnectionUnavailable('Account is unavailable')
    active, keys = keyring()
    payload = json.dumps({'user_id': user_id, 'provider': provider, 'secret': secret}, separators=(',', ':'))
    ciphertext = keys[active].encrypt(payload.encode()).decode()
    from orchestrator_core.storage.transactions import transaction
    from orchestrator_core.core.plans import require_capacity
    with transaction(db):
        count = db.execute('SELECT COUNT(*) FROM connections WHERE user_id=? AND provider<>?', (user_id, provider)).fetchone()[0]
        require_capacity(db, user_id, 'connected_accounts', count)
        db.execute('INSERT INTO connections(user_id,provider,credentials,key_id,scopes,status,created_at) VALUES (?,?,?,?,?,?,?) '
                   "ON CONFLICT(user_id,provider) DO UPDATE SET credentials=excluded.credentials,key_id=excluded.key_id,scopes=excluded.scopes,status='connected',created_at=excluded.created_at,last_used_at=NULL",
                   (user_id, provider, ciphertext, active, json.dumps(sorted(set(scopes))), 'connected', now().isoformat()))
        log_audit(db, user_id, 'provider_connected', 'connection', provider)


def load_connection(db, user_id, provider, required_scopes=()):
    row = db.execute("SELECT connections.* FROM connections JOIN users ON users.id=connections.user_id WHERE user_id=? AND provider=? AND status='connected' AND users.active=1", (user_id, provider)).fetchone()
    if not row:
        raise ConnectionUnavailable('Connect your ' + provider.replace('_', ' ') + ' account')
    active, keys = keyring()
    try:
        payload = json.loads(keys[row['key_id']].decrypt(row['credentials'].encode()))
        if payload['user_id'] != user_id or payload['provider'] != provider:
            raise ValueError()
        if not set(required_scopes).issubset(json.loads(row['scopes'])):
            raise ValueError()
        secret = payload['secret']
        if not isinstance(secret, dict):
            raise ValueError()
    except (InvalidToken, KeyError, ValueError, TypeError):
        raise ConnectionUnavailable('Reconnect this provider account') from None
    with db:
        encrypted = keys[active].encrypt(json.dumps(payload).encode()).decode() if active != row['key_id'] else row['credentials']
        changed = db.execute("UPDATE connections SET credentials=?,key_id=?,last_used_at=? WHERE user_id=? AND provider=? AND credentials=? AND status='connected'",
                             (encrypted, active, now().isoformat(), user_id, provider, row['credentials']))
        if changed.rowcount != 1:
            raise ConnectionUnavailable('Connection changed; retry after reconnecting')
    return secret


def list_connections(db, user_id):
    return [dict(row) for row in db.execute('SELECT provider,scopes,status,created_at,last_used_at FROM connections WHERE user_id=? ORDER BY provider', (user_id,)).fetchall()]


def disconnect(db, user_id, provider):
    with db:
        db.execute('DELETE FROM connections WHERE user_id=? AND provider=?', (user_id, provider))
        log_audit(db, user_id, 'provider_disconnected', 'connection', provider)
