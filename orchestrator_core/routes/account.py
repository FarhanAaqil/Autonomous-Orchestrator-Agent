"""Personal account metadata, usage, and manually administered plan expiry."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, SecretStr
from orchestrator_core.core.ownership import request_owner
from orchestrator_core.core.plans import account_plan, usage_summary, grant_plan
from orchestrator_core.core.connections import list_connections, disconnect
from orchestrator_core.storage.db import get_db_connection

router = APIRouter(prefix='/account', tags=['Account'])


def personal_owner(owner=Depends(request_owner)):
    if owner is None:
        raise HTTPException(401, 'Sign in with a personal account')
    return owner


@router.get('')
def account_summary(db=Depends(get_db_connection), owner=Depends(personal_owner)):
    row = db.execute('SELECT username,email,email_verified_at,execution_mode FROM users WHERE id=? AND active=1', (owner,)).fetchone()
    if not row:
        raise HTTPException(401, 'Account unavailable')
    return {**dict(row), **account_plan(db, owner), 'usage': usage_summary(db, owner)}


@router.get('/connections')
def connections(db=Depends(get_db_connection), owner=Depends(personal_owner)):
    return list_connections(db, owner)


@router.delete('/connections/{provider}')
def disconnect_provider(provider: str, db=Depends(get_db_connection), owner=Depends(personal_owner)):
    disconnect(db, owner, provider)
    return {'disconnected': True}


class PlanGrant(BaseModel):
    plan: str
    paid_until: str | None = None


@router.put('/users/{user_id}/plan')
def change_plan(user_id: str, body: PlanGrant, db=Depends(get_db_connection), owner=Depends(personal_owner)):
    try:
        grant_plan(db, owner, user_id, body.plan, body.paid_until)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    return account_plan(db, user_id)


@router.post('/connections/{provider}/start')
def start_connection(provider: str, request: Request, db=Depends(get_db_connection), owner=Depends(personal_owner)):
    from orchestrator_core.core.oauth import begin
    from orchestrator_core.core.connections import ConnectionUnavailable
    try:
        return {'url': begin(db, owner, provider, request.cookies.get('orchestrator_session'))}
    except ConnectionUnavailable as exc:
        raise HTTPException(400, str(exc)) from None


@router.get('/connections/{provider}/callback')
def finish_connection(provider: str, request: Request, state: str = '', code: str = '', db=Depends(get_db_connection), owner=Depends(personal_owner)):
    from orchestrator_core.core.oauth import complete
    from orchestrator_core.core.connections import ConnectionUnavailable
    try:
        complete(db, owner, provider, request.cookies.get('orchestrator_session'), state, code)
    except ConnectionUnavailable as exc:
        raise HTTPException(400, str(exc)) from None
    return RedirectResponse('/#connection=complete', status_code=303, headers={'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'})


class PersonalToken(BaseModel):
    token: SecretStr


@router.put('/connections/{provider}')
def save_personal_token(provider: str, body: PersonalToken, db=Depends(get_db_connection), owner=Depends(personal_owner)):
    from orchestrator_core.core.connections import validate_personal_token, store_connection, require_connection_capacity, ConnectionUnavailable
    try:
        require_connection_capacity(db, owner, provider)
        secret = validate_personal_token(provider, body.token.get_secret_value())
        store_connection(db, owner, provider, secret, [])
    except ConnectionUnavailable as exc:
        raise HTTPException(400, str(exc)) from None
    return {'connected': True, 'provider': provider}


class ExecutionPreference(BaseModel):
    mode: str


@router.put('/execution-mode')
def execution_preference(body: ExecutionPreference, db=Depends(get_db_connection), owner=Depends(personal_owner)):
    if body.mode not in ('simulation', 'live'):
        raise HTTPException(400, 'Choose simulation or live')
    from orchestrator_core.storage.transactions import transaction
    from orchestrator_core.storage.db import log_audit
    with transaction(db):
        user = db.execute('SELECT email_verified_at FROM users WHERE id=? AND active=1', (owner,)).fetchone()
        if not user or (body.mode == 'live' and not user['email_verified_at']):
            raise HTTPException(403, 'Verify your email before enabling live actions')
        db.execute('UPDATE users SET execution_mode=? WHERE id=?', (body.mode, owner))
        # Pending consent is never repurposed after a preference change.
        db.execute("UPDATE approvals SET status='superseded',version=version+1 WHERE user_id=? AND status IN ('pending','approved') AND execution_mode<>?", (owner, body.mode))
        log_audit(db, owner, 'execution_preference_changed', 'user', owner, {'mode': body.mode})
    return {'mode': body.mode}


@router.get('/users/{user_id}/summary')
def administrator_summary(user_id: str, db=Depends(get_db_connection), owner=Depends(personal_owner)):
    if not db.execute("SELECT 1 FROM users WHERE id=? AND active=1 AND role='administrator'", (owner,)).fetchone():
        raise HTTPException(403, 'Administrator required')
    try:
        return {**account_plan(db, user_id), 'usage': usage_summary(db, user_id)}
    except ValueError:
        raise HTTPException(404, 'Active account not found') from None


@router.get('/export')
def export_account(db=Depends(get_db_connection), owner=Depends(personal_owner)):
    from fastapi.responses import JSONResponse
    from orchestrator_core.core.ownership import OWNED_TABLES
    from orchestrator_core.core.identity import now
    from orchestrator_core.storage.transactions import transaction
    with transaction(db):
        profile = db.execute('SELECT id,username,email,role,created_at,email_verified_at,plan,paid_until,execution_mode FROM users WHERE id=?', (owner,)).fetchone()
        data = {'exported_at': now().isoformat(), 'profile': dict(profile), 'connections': list_connections(db, owner), 'records': {}}
        for table in OWNED_TABLES:
            rows = db.execute(f'SELECT * FROM {table} WHERE user_id=? LIMIT 50001', (owner,)).fetchall()
            if len(rows) > 50000:
                raise HTTPException(413, 'This account requires an administrator-assisted export; no partial export was produced')
            data['records'][table] = [dict(row) for row in rows]
    return JSONResponse(data, headers={'Content-Disposition': 'attachment; filename="toji-account.json"', 'Cache-Control': 'no-store'})
