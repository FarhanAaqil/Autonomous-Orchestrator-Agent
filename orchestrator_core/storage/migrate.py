"""Explicit migrations run with separate credentials; never by the API role."""
import os


def main():
    from dotenv import load_dotenv
    from orchestrator_core.storage.postgres import connect, migrate
    load_dotenv()
    url = os.environ.get('MIGRATION_DATABASE_URL')
    if not url:
        raise SystemExit('MIGRATION_DATABASE_URL is required')
    conn = connect(url, pooled=False)
    try:
        migrate(conn)
    finally:
        conn.close()
    print('PostgreSQL migrations complete.')


if __name__ == '__main__':
    main()
