"""Explicit provider grants with session-bound, single-use state and PKCE."""
import base64
import hashlib
import json
import os
import secrets
from datetime import timedelta
from urllib.parse import urlencode
import requests
from orchestrator_core.core.connections import ConnectionUnavailable, keyring, store_connection, require_connection_capacity
from orchestrator_core.core.identity import digest, now
from orchestrator_core.storage.transactions import transaction

SCOPES = {
    'github': ['read:user', 'repo'],
    'gmail_read': ['https://www.googleapis.com/auth/gmail.readonly'],
    'gmail_send': ['https://www.googleapis.com/auth/gmail.send'],
}


def configuration(provider):
    if provider not in SCOPES:
        raise ConnectionUnavailable('Unsupported OAuth provider')
    github = provider == 'github'
    prefix = 'GITHUB_OAUTH' if github else 'GOOGLE_OAUTH'
    client_id, secret = os.getenv(prefix + '_CLIENT_ID'), os.getenv(prefix + '_CLIENT_SECRET')
    base = os.getenv('PUBLIC_BASE_URL', '').rstrip('/')
    from urllib.parse import urlsplit
    parsed = urlsplit(base)
    if not client_id or not secret or parsed.scheme != 'https' or not parsed.hostname or parsed.query or parsed.fragment or parsed.username:
        raise ConnectionUnavailable('This provider needs operator configuration before connection')
    return {
        'client_id': client_id, 'client_secret': secret,
        'redirect_uri': base + '/account/connections/' + provider + '/callback',
        'authorize': 'https://github.com/login/oauth/authorize' if github else 'https://accounts.google.com/o/oauth2/v2/auth',
        'token': 'https://github.com/login/oauth/access_token' if github else 'https://oauth2.googleapis.com/token',
    }


def require_email_beta(db, owner):
    row = db.execute('SELECT email FROM users WHERE id=? AND active=1', (owner,)).fetchone()
    allowed = {value.strip().lower() for value in os.getenv('GMAIL_BETA_EMAILS', '').split(',') if value.strip()}
    if not row or (row['email'] or '').lower() not in allowed:
        raise ConnectionUnavailable('Gmail is in private beta; ask the administrator for access')


def begin(db, owner, provider, session):
    require_connection_capacity(db, owner, provider)
    config = configuration(provider)
    if not session:
        raise ConnectionUnavailable('Sign in again before connecting an account')
    if provider.startswith('gmail_'):
        require_email_beta(db, owner)
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    key_id, keys = keyring()
    envelope = json.dumps({'owner': owner, 'provider': provider, 'verifier': verifier})
    encrypted = keys[key_id].encrypt(envelope.encode()).decode()
    with transaction(db):
        db.execute('DELETE FROM oauth_states WHERE expires_at<? OR (user_id=? AND provider=?)', (now().isoformat(), owner, provider))
        db.execute('INSERT INTO oauth_states(state_hash,user_id,provider,session_hash,verifier,key_id,expires_at) VALUES (?,?,?,?,?,?,?)',
                   (digest(state), owner, provider, digest(session), encrypted, key_id, (now()+timedelta(minutes=10)).isoformat()))
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    params = {key: config[key] for key in ('client_id', 'redirect_uri')}
    params.update(response_type='code', state=state, scope=' '.join(SCOPES[provider]), code_challenge=challenge, code_challenge_method='S256')
    if provider.startswith('gmail_'):
        params.update(access_type='offline', prompt='consent', include_granted_scopes='false')
    return config['authorize'] + '?' + urlencode(params)


def json_response(response):
    if response.status_code not in (200, 201):
        raise ConnectionUnavailable('Provider rejected the connection; reconnect and check its permissions')
    try:
        data = response.json()
        if not isinstance(data, dict) or data.get('error') or data.get('errors'):
            raise ValueError()
        return data
    except ValueError:
        raise ConnectionUnavailable('Provider returned an invalid response') from None


def complete(db, owner, provider, session, state, code):
    config = configuration(provider)
    if provider.startswith('gmail_'):
        require_email_beta(db, owner)
    with transaction(db):
        row = db.execute('DELETE FROM oauth_states WHERE state_hash=? AND user_id=? AND provider=? AND session_hash=? AND expires_at>? RETURNING *',
                         (digest(state), owner, provider, digest(session or ''), now().isoformat())).fetchone()
    if not row:
        raise ConnectionUnavailable('Connection request expired or does not belong to this session')
    try:
        _, keys = keyring()
        envelope = json.loads(keys[row['key_id']].decrypt(row['verifier'].encode()))
        if envelope['owner'] != owner or envelope['provider'] != provider:
            raise ValueError()
        payload = {key: config[key] for key in ('client_id', 'client_secret', 'redirect_uri')}
        payload.update(code=code, code_verifier=envelope['verifier'], grant_type='authorization_code')
        data = json_response(requests.post(config['token'], data=payload, headers={'Accept': 'application/json'}, timeout=15, allow_redirects=False))
        scopes = set(str(data.get('scope', '')).replace(',', ' ').split())
        if not set(SCOPES[provider]).issubset(scopes) or not data.get('access_token'):
            raise ConnectionUnavailable('The required permissions were not granted')
        secret = {'access_token': data['access_token']}
        if data.get('refresh_token'):
            secret['refresh_token'] = data['refresh_token']
        if data.get('expires_in'):
            secret['expires_at'] = (now()+timedelta(seconds=int(data['expires_in']))).isoformat()
        if provider == 'github':
            profile = json_response(requests.get('https://api.github.com/user', headers={'Authorization': 'Bearer '+data['access_token'], 'Accept': 'application/vnd.github+json'}, timeout=15, allow_redirects=False))
            secret['login'] = profile['login']
        store_connection(db, owner, provider, secret, scopes)
    except ConnectionUnavailable:
        raise
    except Exception:
        raise ConnectionUnavailable('Connection could not be completed; start again') from None
