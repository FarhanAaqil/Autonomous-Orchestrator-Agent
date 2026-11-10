"""Disposable browser fixture server. Never loads .env or production credentials."""
import argparse
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import dotenv
dotenv.load_dotenv = lambda *args, **kwargs: False
parser = argparse.ArgumentParser()
parser.add_argument('--worker', action='store_true')
args = parser.parse_args()
state = Path(os.environ.get('PHASE3_STATE', tempfile.mkdtemp(prefix='toji-browser-')))
state.mkdir(parents=True, exist_ok=True)
os.environ.update(DATABASE_URL='', MIGRATION_DATABASE_URL='', DATABASE_PATH=str(state/'browser.db'),
                  CHROMA_DB_DIR=str(state/'chroma'), AUTH_TOKEN='browser-fixture-service-only',
                  GROQ_API_KEY='', ALLOW_INSECURE_LOCAL='false', ENVIRONMENT='development',
                  ACTION_EXECUTION_MODE='simulation', ENABLE_REAL_EMAIL='false',
                  EXECUTOR_HMAC_SECRET='browser-fixture-only-signing-secret-32')
if args.worker:
    from orchestrator_core.jobs.worker import Worker
    Worker(poll_interval=60).start()
    import time
    while True:
        time.sleep(1)
else:
    from orchestrator_core.storage.db import get_db, run_migrations
    from orchestrator_core.core.identity import create_user
    from orchestrator_core.core.approval_gate import request_approval
    db = get_db()
    run_migrations(db)
    if not db.execute('SELECT 1 FROM users').fetchone():
        create_user(db, 'browser-admin', 'browser-fixture-password-123', 'administrator')
        create_user(db, 'browser-viewer', 'browser-fixture-password-123', 'viewer')
        create_user(db, 'browser-operator', 'browser-fixture-password-123', 'operator')
        request_approval('send_email', {'to':'fixture@example.com','subject':'Browser review fixture','body':'Offline simulation only.'}, db)
        from datetime import datetime, timedelta, timezone
        with db:
            db.execute("INSERT INTO conversations(id,title) VALUES ('long-history','Long history fixture')")
            for index in range(520):
                timestamp = (datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=index)).isoformat()
                db.execute("INSERT INTO messages(id,conversation_id,role,content,created_at) VALUES (?,'long-history','assistant',?,?)", (str(index),f'history-message-{index}',timestamp))
    with db:
        db.execute("UPDATE system_flags SET value='on' WHERE key='kill_switch'")
        db.execute('UPDATE schedules SET is_active=0')
    db.close()
    import subprocess
    worker = subprocess.Popen([sys.executable, __file__, '--worker'], env={**os.environ,'PHASE3_STATE':str(state)})
    try:
        from orchestrator_core.main import app
        import uvicorn
        uvicorn.run(app, host='127.0.0.1', port=8081, access_log=False)
    finally:
        worker.terminate()
        worker.wait(timeout=10)
