"""Single-use account challenges. Plaintext tokens exist only during mail delivery."""
import re
import secrets
from datetime import timedelta

from orchestrator_core.core.identity import digest, now, password_hash
from orchestrator_core.storage.db import log_audit


def normalize_email(value):
    value = value.strip().lower()
    if len(value) > 100 or not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}", value):
        raise ValueError('Enter a valid email address of at most 100 characters')
    return value


def reserve_attempt(db, purpose, account, address):
    timestamp = now()
    keys = [(purpose + ':account:' + digest(account), 5), (purpose + ':address:' + digest(address), 30)]
    db.execute('BEGIN IMMEDIATE')
    try:
        for key, maximum in keys:
            row = db.execute('SELECT * FROM login_limits WHERE key=?', (key,)).fetchone()
            if row and row['reset_at'] > timestamp.isoformat() and row['attempts'] >= maximum:
                db.rollback()
                return False
        for key, _ in keys:
            db.execute('INSERT INTO login_limits(key,attempts,reset_at) VALUES (?,1,?) '
                       'ON CONFLICT(key) DO UPDATE SET attempts=CASE WHEN login_limits.reset_at<=? THEN 1 ELSE login_limits.attempts+1 END, '
                       'reset_at=CASE WHEN login_limits.reset_at<=? THEN excluded.reset_at ELSE login_limits.reset_at END',
                       (key, (timestamp+timedelta(minutes=15)).isoformat(), timestamp.isoformat(), timestamp.isoformat()))
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return True


def issue_token(db, user_id, purpose):
    if purpose not in ('verify', 'reset'):
        raise ValueError('Invalid challenge purpose')
    token = secrets.token_urlsafe(48)
    timestamp = now()
    with db:
        db.execute('DELETE FROM account_tokens WHERE user_id=? AND purpose=?', (user_id, purpose))
        db.execute('INSERT INTO account_tokens VALUES (?,?,?,?,?)',
                   (digest(token), user_id, purpose, (timestamp+timedelta(hours=24 if purpose == 'verify' else 1)).isoformat(), timestamp.isoformat()))
    return token


def consume_token(db, token, purpose, password=None):
    encoded = password_hash(password) if purpose == 'reset' else None
    db.execute('BEGIN IMMEDIATE')
    try:
        row = db.execute('SELECT account_tokens.* FROM account_tokens JOIN users ON users.id=account_tokens.user_id '
                         'WHERE token_hash=? AND purpose=? AND expires_at>? AND users.active=1',
                         (digest(token), purpose, now().isoformat())).fetchone()
        if not row:
            raise ValueError('This link is invalid or expired; request a new one')
        if purpose == 'reset':
            db.execute('UPDATE users SET password_hash=?,version=version+1 WHERE id=?', (encoded, row['user_id']))
            db.execute('DELETE FROM sessions WHERE user_id=?', (row['user_id'],))
            db.execute("DELETE FROM account_tokens WHERE user_id=? AND purpose='reset'", (row['user_id'],))
        else:
            db.execute('UPDATE users SET email_verified_at=? WHERE id=?', (now().isoformat(), row['user_id']))
            db.execute('DELETE FROM account_tokens WHERE token_hash=?', (digest(token),))
        log_audit(db, row['user_id'], 'email_verified' if purpose == 'verify' else 'password_reset', 'user', row['user_id'])
        db.commit()
    except BaseException:
        db.rollback()
        raise
