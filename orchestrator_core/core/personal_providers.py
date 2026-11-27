"""Read-only requests using only the current account's encrypted grants."""
from contextlib import contextmanager
from datetime import datetime, timedelta
import json
import requests
from orchestrator_core.core.connections import ConnectionUnavailable, keyring, load_connection
from orchestrator_core.core.identity import now
from orchestrator_core.core.ownership import execution_owner
from orchestrator_core.core.usage import usage_db
from orchestrator_core.core.oauth import configuration, json_response, require_email_beta
from orchestrator_core.storage.db import get_db


@contextmanager
def owner_database():
    owner = execution_owner.get()
    if not owner:
        raise ConnectionUnavailable('Sign in with your own account before connecting a provider')
    db = usage_db.get()
    own = db is None
    db = db or get_db()
    try:
        yield db, owner
    finally:
        if own:
            db.close()


def access_token(db, owner, provider, scopes=()):
    if provider.startswith('gmail_'):
        require_email_beta(db, owner)
    before = db.execute('SELECT credentials FROM connections WHERE user_id=? AND provider=?', (owner, provider)).fetchone()
    secret = load_connection(db, owner, provider, scopes)
    if not secret.get('access_token'):
        raise ConnectionUnavailable('Reconnect your ' + provider + ' account')
    if secret.get('expires_at') and datetime.fromisoformat(secret['expires_at']) <= now()+timedelta(seconds=60):
        if not secret.get('refresh_token'):
            raise ConnectionUnavailable('Reconnect your ' + provider + ' account')
        config = configuration(provider)
        if not before:
            raise ConnectionUnavailable('Connection was removed')
        try:
            data = json_response(requests.post(config['token'], data={'client_id': config['client_id'], 'client_secret': config['client_secret'], 'grant_type': 'refresh_token', 'refresh_token': secret['refresh_token']}, headers={'Accept': 'application/json'}, timeout=15, allow_redirects=False))
            secret['access_token'] = data['access_token']
            secret['expires_at'] = (now()+timedelta(seconds=int(data['expires_in']))).isoformat()
            if data.get('refresh_token'):
                secret['refresh_token'] = data['refresh_token']
            key_id, keys = keyring()
            encrypted = keys[key_id].encrypt(json.dumps({'user_id': owner, 'provider': provider, 'secret': secret}).encode()).decode()
            with db:
                changed = db.execute("UPDATE connections SET credentials=?,key_id=? WHERE user_id=? AND provider=? AND credentials=? AND status='connected'", (encrypted, key_id, owner, provider, before['credentials']))
                if changed.rowcount != 1:
                    raise ConnectionUnavailable('Connection changed; retry after reconnecting')
        except ConnectionUnavailable:
            raise
        except Exception:
            raise ConnectionUnavailable('Provider renewal failed; reconnect this account') from None
    return secret['access_token']


def github_read(endpoint):
    if not endpoint.startswith('/') or endpoint.startswith('//') or '..' in endpoint or '\\' in endpoint:
        raise ConnectionUnavailable('Invalid GitHub resource')
    with owner_database() as (db, owner):
        token = access_token(db, owner, 'github')
        try:
            response = requests.get('https://api.github.com'+endpoint, headers={'Authorization': 'Bearer '+token, 'Accept': 'application/vnd.github+json'}, timeout=15, allow_redirects=False)
            if response.status_code != 200:
                raise ConnectionUnavailable('GitHub resource unavailable; check your connection and permissions')
            return response.json()
        except requests.RequestException:
            raise ConnectionUnavailable('GitHub is unavailable; retry later') from None


def gmail_inbox(max_messages=5):
    with owner_database() as (db, owner):
        token = access_token(db, owner, 'gmail_read', ['https://www.googleapis.com/auth/gmail.readonly'])
        headers = {'Authorization': 'Bearer '+token}
        base = 'https://gmail.googleapis.com/gmail/v1/users/me/messages'
        try:
            items = json_response(requests.get(base, params={'q': 'is:unread', 'maxResults': min(10, max(1, max_messages))}, headers=headers, timeout=15, allow_redirects=False))
            from urllib.parse import quote
            summaries = []
            for item in items.get('messages', []):
                data = json_response(requests.get(base+'/'+quote(item['id'], safe=''), params={'format': 'metadata', 'metadataHeaders': ['From', 'Subject', 'Date']}, headers=headers, timeout=15, allow_redirects=False))
                fields = {field['name'].lower(): field['value'] for field in data.get('payload', {}).get('headers', [])}
                summaries.append('- '+fields.get('from', 'Unknown sender')+': '+fields.get('subject', 'No subject'))
            return '\n'.join(summaries) if summaries else 'No unread messages in your connected Gmail account.'
        except requests.RequestException:
            raise ConnectionUnavailable('Gmail is unavailable; retry later') from None
