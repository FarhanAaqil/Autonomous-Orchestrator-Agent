"""Local recovery only: python -m orchestrator_core.reset_password --username admin."""
import argparse
import sys
from getpass import getpass

from orchestrator_core.core.identity import digest, password_hash
from orchestrator_core.storage.db import get_db, log_audit


def reset_password(db, username, password):
    username = username.strip().lower()
    encoded = password_hash(password)
    db.execute('BEGIN IMMEDIATE')
    try:
        user = db.execute('SELECT id,active FROM users WHERE username=?', (username,)).fetchone()
        if not user or not user['active']:
            raise ValueError('Active account not found')
        db.execute('UPDATE users SET password_hash=?,version=version+1 WHERE id=?',
                   (encoded, user['id']))
        db.execute('DELETE FROM sessions WHERE user_id=?', (user['id'],))
        db.execute('DELETE FROM login_limits WHERE key=?', ('account:' + digest(username),))
        log_audit(db, 'local-recovery', 'password_reset', 'user', user['id'])
        db.commit()
    except BaseException:
        db.rollback()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--username', default='admin')
    args = parser.parse_args()
    if not sys.stdin.isatty():
        raise SystemExit('An interactive terminal is required. Use docker exec -it.')
    try:
        password = getpass('New password (14-1024 characters; typing is hidden): ')
        if password != getpass('Repeat new password: '):
            raise ValueError('Passwords did not match; nothing changed')
        db = get_db()
        try:
            reset_password(db, args.username, password)
        finally:
            db.close()
    except (ValueError, EOFError, KeyboardInterrupt) as exc:
        raise SystemExit(str(exc) or 'Password reset cancelled') from None
    print('Password reset. Previous sessions revoked. Sign in with your new password.')


if __name__ == '__main__':
    main()
