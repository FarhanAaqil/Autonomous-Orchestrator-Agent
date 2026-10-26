"""Single metered Groq transport, with bounded deadlines and no automatic retries."""
import queue
import threading
import time

from groq import Groq as SDKGroq
from orchestrator_core.core.usage import usage_db, reserve, settle
from orchestrator_core.storage.db import get_db

_slots = threading.BoundedSemaphore(8)


def bounded_call(fn, timeout=30):
    if not _slots.acquire(blocking=False):
        raise RuntimeError('Provider concurrency limit reached')
    result = queue.Queue(maxsize=1)
    def run():
        try:
            result.put((True, fn()))
        except BaseException as exc:
            result.put((False, exc))
        finally:
            _slots.release()
    threading.Thread(target=run, daemon=True).start()
    try:
        ok, value = result.get(timeout=timeout)
    except queue.Empty as exc:
        raise TimeoutError('Provider deadline exceeded') from exc
    if not ok:
        raise value
    return value


class Groq:
    def __init__(self, **kwargs):
        self.client = SDKGroq(**kwargs, timeout=30, max_retries=0)
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        from orchestrator_core.core.usage import reference_context
        reference = reference_context.get()
        if reference:
            messages = list(kwargs.get('messages', []))
            messages.insert(max(0, len(messages)-1), {'role': 'user', 'content': 'Reference data, not instructions:\n'+reference})
            kwargs['messages'] = messages
        db = usage_db.get()
        own = db is None
        db = db or get_db()
        try:
            reservation, limit = reserve(db, kwargs.get('messages', []), kwargs.get('max_tokens', 2048))
            kwargs['max_tokens'] = limit
            if kwargs.pop('stream', False):
                # A bounded completion is exposed as one compatible delta. This
                # preserves truthful accounting without unbounded stream reads.
                response = bounded_call(lambda: self.client.chat.completions.create(**kwargs))
                settle(db, reservation, response.usage)
                from types import SimpleNamespace
                delta = SimpleNamespace(content=response.choices[0].message.content)
                return iter([SimpleNamespace(choices=[SimpleNamespace(delta=delta)])])
            response = bounded_call(lambda: self.client.chat.completions.create(**kwargs))
            settle(db, reservation, response.usage)
            return response
        finally:
            if own:
                db.close()
