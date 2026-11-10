"""Explicit worker/scheduler processes and dependency readiness."""
import argparse
import os
import signal
import threading
from datetime import datetime, timedelta, timezone

from orchestrator_core.storage.db import get_db, run_migrations


def beat(role):
    db = get_db()
    try:
        with db:
            db.execute('INSERT INTO service_heartbeats (role,beat_at) VALUES (?,?) ON CONFLICT(role) DO UPDATE SET beat_at=excluded.beat_at',
                       (role, datetime.now(timezone.utc).isoformat()))
    finally:
        db.close()


def readiness(db):
    import httpx
    cutoff = (datetime.now(timezone.utc)-timedelta(seconds=45)).isoformat()
    roles = {r['role'] for r in db.execute('SELECT role FROM service_heartbeats WHERE beat_at>?', (cutoff,)).fetchall()}
    checks = {'database': True, 'worker': 'worker' in roles, 'scheduler': 'scheduler' in roles}
    sandbox = os.environ.get('SANDBOX_BROWSER_URL')
    checks['sandbox'] = False
    if sandbox:
        try:
            checks['sandbox'] = httpx.get(sandbox.rstrip('/')+'/health', timeout=2).is_success
        except httpx.HTTPError:
            pass
    return checks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('role', choices=['worker', 'scheduler'])
    role = parser.parse_args().role
    db = get_db()
    try:
        run_migrations(db)
    finally:
        db.close()
    stop = threading.Event()
    def heartbeat():
        while not stop.is_set():
            beat(role)
            stop.wait(10)
    threading.Thread(target=heartbeat, daemon=True).start()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    from orchestrator_core.jobs.worker import Worker
    from orchestrator_core.core.scheduler import _tick
    worker = Worker()
    import logging
    try:
        while not stop.is_set():
            try:
                worker.run_once() if role == 'worker' else _tick()
            except Exception:
                logging.exception('%s cycle failed', role)
            stop.wait(1 if role == 'worker' else 5)
    finally:
        stop.set()


if __name__ == '__main__':
    main()
