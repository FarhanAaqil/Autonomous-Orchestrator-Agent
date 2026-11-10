"""Durable SSE replay shared by API and worker processes."""
import asyncio
import json


class JobEventHub:
    def __init__(self, history_size=200):
        self.history_size = history_size

    def publish(self, event_type, data, db=None):
        if event_type.startswith('job.'):
            return  # Database triggers capture these atomically.
        from orchestrator_core.storage.db import get_db
        from orchestrator_core.storage.transactions import transaction
        own = db is None
        db = db or get_db()
        try:
            with transaction(db):
                if getattr(db, 'dialect', None) == 'postgresql':
                    db.execute('SELECT pg_advisory_xact_lock(74201903)')
                db.execute('INSERT INTO job_events(event,data_json) VALUES (?,?)', (event_type, json.dumps(data)))
        finally:
            if own:
                db.close()

    def read(self, after, session_token=None):
        from orchestrator_core.storage.db import get_db
        from orchestrator_core.core.identity import principal
        db = get_db()
        try:
            if session_token and not principal(db, session_token):
                return None, None
            bounds = db.execute('SELECT MIN(id),MAX(id) FROM job_events').fetchone()
            rows = db.execute('SELECT * FROM job_events WHERE id>? ORDER BY id LIMIT 100', (after,)).fetchall()
            return bounds, [dict(row) for row in rows]
        finally:
            db.close()

    async def subscribe(self, last_event_id=None, session_token=None):
        try:
            cursor = max(0, int(last_event_id or 0))
        except ValueError:
            cursor = 0
        yield ': connected\n\n'
        first = True
        while True:
            bounds, rows = await asyncio.to_thread(self.read, cursor, session_token)
            if rows is None:
                yield 'event: session.expired\ndata: {}\n\n'
                return
            minimum, maximum = bounds[0] or 0, bounds[1] or 0
            if first and (cursor > maximum or (cursor and cursor < minimum-1)):
                cursor = maximum
                yield f'id: {cursor}\nevent: snapshot.required\ndata: {{}}\n\n'
                rows = []
            first = False
            for row in rows:
                cursor = row['id']
                payload = json.dumps({'id': cursor, 'event': row['event'], 'data': json.loads(row['data_json'])})
                yield f"id: {cursor}\nevent: {row['event']}\ndata: {payload}\n\n"
            if not rows:
                yield ': ping\n\n'
                await asyncio.sleep(1)


event_hub = JobEventHub()
