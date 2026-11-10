"""One-time administrator bootstrap: python -m orchestrator_core.bootstrap."""
import argparse
from getpass import getpass


def main():
    from orchestrator_core.storage.db import get_db
    from orchestrator_core.core.identity import create_user
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--username', default='admin')
    args = parser.parse_args()
    password = getpass('Administrator password (14+ characters): ')
    if password != getpass('Repeat password: '):
        raise SystemExit('Passwords did not match')
    db = get_db()
    try:
        create_user(db, args.username, password, 'administrator', bootstrap=True, actor='local-bootstrap')
    finally:
        db.close()
    print('Administrator created. Sign in through /auth/login.')


if __name__ == '__main__':
    main()
