"""Human account lifecycle; no public registration or password recovery."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from orchestrator_core.config import get_settings
from orchestrator_core.core import identity
from orchestrator_core.dependencies import verify_bearer_token
from orchestrator_core.storage.db import get_db_connection

router = APIRouter(prefix='/auth', tags=['Authentication'])


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=1024, repr=False)


@router.post('/login')
def login(body: Credentials, request: Request, response: Response, db=Depends(get_db_connection)):
    # Fetch Metadata protects login CSRF without trusting forwarded headers.
    if request.headers.get('sec-fetch-site') == 'cross-site':
        raise HTTPException(403, 'Cross-site login is not allowed')
    origin = request.headers.get('origin')
    if origin and origin.rstrip('/') != str(request.base_url).rstrip('/'):
        raise HTTPException(403, 'Cross-site login is not allowed')
    token = identity.login(db, body.username, body.password, request.client.host if request.client else 'unknown')
    if not token:
        raise HTTPException(401, 'Unable to sign in; check credentials or retry later')
    old = request.cookies.get('orchestrator_session')
    if old:
        identity.logout(db, old)
    response.set_cookie('orchestrator_session', token, httponly=True,
                        secure=get_settings().environment != 'development', samesite='strict', max_age=8*3600, path='/')
    response.headers['Cache-Control'] = 'no-store'
    return {'user': identity.principal(db, token), 'csrf_token': identity.csrf_token(token)}


@router.get('/session', dependencies=[Depends(verify_bearer_token)])
def session(request: Request, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    token = request.cookies.get('orchestrator_session')
    return {'user': request.state.principal, 'csrf_token': identity.csrf_token(token) if token else None}


@router.post('/logout', dependencies=[Depends(verify_bearer_token)])
def logout(request: Request, response: Response, db=Depends(get_db_connection)):
    token = request.cookies.get('orchestrator_session')
    if token:
        identity.logout(db, token)
    response.delete_cookie('orchestrator_session', path='/')
    return {'signed_out': True}


class AccountCreate(Credentials):
    role: str = 'operator'


@router.get('/users', dependencies=[Depends(verify_bearer_token)])
def list_users(request: Request, db=Depends(get_db_connection)):
    if request.state.principal['role'] != 'administrator':
        raise HTTPException(403, 'Only administrators can list accounts')
    return [dict(row) for row in db.execute('SELECT id,username,role,active FROM users ORDER BY username').fetchall()]


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=1024, repr=False)
    new_password: str = Field(min_length=14, max_length=1024, repr=False)


@router.post('/password', dependencies=[Depends(verify_bearer_token)])
def change_password(body: PasswordChange, request: Request, response: Response, db=Depends(get_db_connection)):
    from argon2.exceptions import VerificationError
    from orchestrator_core.storage.db import log_audit
    user_id = request.state.principal['id']
    user = db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
    try:
        if not user or not identity.hasher.verify(user['password_hash'], body.current_password):
            raise HTTPException(401, 'Password verification failed')
    except VerificationError as exc:
        raise HTTPException(401, 'Password verification failed') from exc
    encoded = identity.password_hash(body.new_password)
    with db:
        cur = db.execute('UPDATE users SET password_hash=?,version=version+1 WHERE id=? AND version=?',
                         (encoded, user_id, user['version']))
        if cur.rowcount != 1:
            raise HTTPException(409, 'Account changed; sign in again')
        db.execute('DELETE FROM sessions WHERE user_id=?', (user_id,))
        log_audit(db, user_id, 'password_changed', 'user', user_id)
    response.delete_cookie('orchestrator_session', path='/')
    return {'changed': True, 'sessions_revoked': True}


@router.post('/users', dependencies=[Depends(verify_bearer_token)], status_code=201)
def create_user(body: AccountCreate, request: Request, db=Depends(get_db_connection)):
    try:
        return identity.create_user(db, body.username, body.password, body.role, actor=request.state.principal['id'])
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


class AccessChange(BaseModel):
    role: str
    active: bool


@router.patch('/users/{user_id}', dependencies=[Depends(verify_bearer_token)])
def change_access(user_id: str, body: AccessChange, request: Request, db=Depends(get_db_connection)):
    try:
        identity.change_access(db, user_id, body.role, body.active, request.state.principal['id'])
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {'changed': True, 'sessions_revoked': True}
