"""Local identities, bounded login attempts, and revocable opaque sessions."""
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from orchestrator_core.storage.db import log_audit

hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
_dummy = hasher.hash(secrets.token_urlsafe(32))


def now():
    return datetime.now(timezone.utc)


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def csrf_token(token):
    return digest('csrf:' + token)


def password_hash(password):
    if not 14 <= len(password) <= 1024:
        raise ValueError('Use a password between 14 and 1024 characters')
    return hasher.hash(password)


def create_user(db, username, password, role='operator', *, bootstrap=False, actor='administrator'):
    username = username.strip().lower()
    if not username or len(username) > 100 or role not in ('administrator', 'operator', 'viewer'):
        raise ValueError('Invalid username or role')
    encoded = password_hash(password)
    user_id = str(uuid.uuid4())
    db.execute('BEGIN IMMEDIATE')
    try:
        if bootstrap and db.execute('SELECT 1 FROM users LIMIT 1').fetchone():
            raise ValueError('Bootstrap is unavailable after the first account exists')
        db.execute('INSERT INTO users (id,username,password_hash,role,created_at) VALUES (?,?,?,?,?)',
                   (user_id, username, encoded, role, now().isoformat()))
        log_audit(db, actor, 'account_created', 'user', user_id, {'role': role})
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return {'id': user_id, 'username': username, 'role': role}


def login(db, username, password, address):
    username = username.strip().lower()
    keys = ['account:' + digest(username), 'address:' + digest(address)]
    current = now()
    # Reserve an attempt before the expensive password check, including failures
    # for usernames that do not exist. Account limit 5; address limit 30/15 min.
    db.execute('BEGIN IMMEDIATE')
    try:
        for key, maximum in zip(keys, (5, 30)):
            row = db.execute('SELECT * FROM login_limits WHERE key=?', (key,)).fetchone()
            if row and row['reset_at'] > current.isoformat() and row['attempts'] >= maximum:
                db.rollback()
                return None
        for key in keys:
            db.execute('INSERT INTO login_limits (key,attempts,reset_at) VALUES (?,1,?) '
                       'ON CONFLICT(key) DO UPDATE SET attempts=CASE WHEN login_limits.reset_at<=? THEN 1 ELSE login_limits.attempts+1 END, '
                       'reset_at=CASE WHEN login_limits.reset_at<=? THEN excluded.reset_at ELSE login_limits.reset_at END',
                       (key, (current + timedelta(minutes=15)).isoformat(), current.isoformat(), current.isoformat()))
        db.commit()
    except BaseException:
        db.rollback()
        raise
    row = db.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
    try:
        valid = hasher.verify(row['password_hash'] if row else _dummy, password)
    except (VerificationError, InvalidHashError):
        valid = False
    if not valid or not row or not row['active']:
        log_audit(db, 'anonymous', 'login_failed', 'authentication', detail={'account_key': keys[0]})
        return None
    token = secrets.token_urlsafe(48)
    expires = (current + timedelta(hours=8)).isoformat()
    with db:
        # Binding to the observed version prevents a concurrent disable/reset
        # from making this in-flight authentication usable.
        db.execute('INSERT INTO sessions (token_hash,user_id,user_version,expires_at,created_at) VALUES (?,?,?,?,?)',
                   (digest(token), row['id'], row['version'], expires, current.isoformat()))
        log_audit(db, row['id'], 'login_succeeded', 'user', row['id'])
    return token


def principal(db, token):
    row = db.execute('SELECT users.id,users.username,users.role FROM sessions JOIN users ON users.id=sessions.user_id '
                     'WHERE sessions.token_hash=? AND sessions.expires_at>? AND users.active=1 AND users.version=sessions.user_version',
                     (digest(token), now().isoformat())).fetchone()
    return dict(row) if row else None


def logout(db, token):
    user = principal(db, token)
    with db:
        db.execute('DELETE FROM sessions WHERE token_hash=?', (digest(token),))
        if user:
            log_audit(db, user['id'], 'logout', 'user', user['id'])


def change_access(db, user_id, role, active, actor):
    if role not in ('administrator', 'operator', 'viewer'):
        raise ValueError('Invalid role')
    db.execute('BEGIN IMMEDIATE')
    try:
        old = db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
        if not old:
            raise ValueError('Account not found')
        if old['role'] == 'administrator' and old['active'] and (role != 'administrator' or not active):
            if db.execute("SELECT COUNT(*) FROM users WHERE role='administrator' AND active=1").fetchone()[0] <= 1:
                raise ValueError('The last active administrator cannot be removed')
        db.execute('UPDATE users SET role=?,active=?,version=version+1 WHERE id=?', (role, int(active), user_id))
        db.execute('DELETE FROM sessions WHERE user_id=?', (user_id,))
        log_audit(db, actor, 'account_access_changed', 'user', user_id, {'role': role, 'active': active})
        db.commit()
    except BaseException:
        db.rollback()
        raise
