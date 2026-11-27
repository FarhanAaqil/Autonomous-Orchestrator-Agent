"""Bound synchronous work fairly in the single API process."""
from contextlib import contextmanager
from threading import Lock
from fastapi import Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from orchestrator_core.core.ownership import request_owner
from orchestrator_core.core.plans import account_plan, reserve_synchronous_run, PlanLimitExceeded
from orchestrator_core.storage.db import get_db_connection

_lock = Lock()
_active = {}
_GLOBAL_LIMIT = 8


@contextmanager
def slot(owner, limit):
    key = owner or 'local-workspace'
    with _lock:
        if _active.get(key, 0) >= limit:
            raise HTTPException(429, 'Your account has work in progress; retry shortly', headers={'Retry-After': '1'})
        if sum(_active.values()) >= _GLOBAL_LIMIT:
            raise HTTPException(503, 'Execution capacity is full; retry shortly', headers={'Retry-After': '1'})
        _active[key] = _active.get(key, 0) + 1
    try:
        yield
    finally:
        with _lock:
            _active[key] -= 1
            if not _active[key]:
                del _active[key]


def limits(db, owner):
    if owner is None:
        return 2
    return account_plan(db, owner)['limits']['concurrent_runs']


async def admit_request(request: Request, owner=Depends(request_owner), db=Depends(get_db_connection)):
    expensive = request.method in ('POST', 'PUT') and request.url.path.startswith(('/dispatch', '/route', '/pipeline', '/approvals', '/account/connections'))
    if not expensive:
        yield
        return
    limit = await run_in_threadpool(limits, db, owner)
    with slot(owner, limit):
        if request.url.path.rstrip('/') in ('/dispatch', '/dispatch/stream', '/route'):
            try:
                await run_in_threadpool(reserve_synchronous_run, db, owner, request.url.path)
            except PlanLimitExceeded as exc:
                raise HTTPException(429, str(exc)) from None
        yield
