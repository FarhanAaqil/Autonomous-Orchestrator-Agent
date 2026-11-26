"""Human accounts with opt-in verified registration and single-use recovery."""
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
        db.execute("DELETE FROM account_tokens WHERE user_id=? AND purpose='reset'", (user_id,))
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


class Signup(BaseModel):
    email: str = Field(max_length=100)
    password: str = Field(min_length=14, max_length=1024, repr=False)


class EmailRequest(BaseModel):
    email: str = Field(max_length=100)


class Challenge(BaseModel):
    token: str = Field(min_length=32, max_length=256, repr=False)


class ResetChallenge(Challenge):
    password: str = Field(min_length=14, max_length=1024, repr=False)


def public_account_request(request, db, purpose, account):
    from orchestrator_core.core.account_recovery import reserve_attempt
    if not get_settings().public_registration:
        raise HTTPException(404, 'Public accounts are not enabled')
    origin = request.headers.get('origin')
    if request.headers.get('sec-fetch-site') == 'cross-site' or (origin and origin.rstrip('/') != str(request.base_url).rstrip('/')):
        raise HTTPException(403, 'Cross-site account requests are not allowed')
    address = request.client.host if request.client else 'unknown'
    if not reserve_attempt(db, purpose, account, address):
        raise HTTPException(429, 'Please wait before trying again', headers={'Retry-After': '900'})


def deliver_challenge(db, user, purpose):
    from orchestrator_core.core.account_recovery import issue_token
    from orchestrator_core.core.mailer import send_account_link
    token = issue_token(db, user['id'], purpose)
    try:
        send_account_link(user['email'], purpose, token)
    except Exception:
        # Never log SMTP responses, recipients or token values; responses do not reveal account existence.
        import logging
        logging.getLogger(__name__).warning('Account email delivery failed')


@router.post('/register', status_code=202)
def register(body: Signup, request: Request, db=Depends(get_db_connection)):
    from orchestrator_core.core.account_recovery import normalize_email
    try:
        email = normalize_email(body.email)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    public_account_request(request, db, 'register', email)
    user = db.execute('SELECT id,email,email_verified_at FROM users WHERE email=?', (email,)).fetchone()
    if user is None:
        import sqlite3
        import psycopg
        try:
            identity.create_user(db, email, body.password, verified=False, actor='registration')
        except (sqlite3.IntegrityError, psycopg.IntegrityError):
            pass  # Concurrent registration uses the same response.
        user = db.execute('SELECT id,email,email_verified_at FROM users WHERE email=?', (email,)).fetchone()
    else:
        identity.password_hash(body.password)  # Comparable password work for existing accounts.
    if user and not user['email_verified_at']:
        deliver_challenge(db, user, 'verify')
    return {'message': 'If this address is eligible, check your email for a verification link.'}


@router.post('/verify')
def verify_email(body: Challenge, request: Request, db=Depends(get_db_connection)):
    from orchestrator_core.core.account_recovery import consume_token
    public_account_request(request, db, 'verify', identity.digest(body.token))
    try:
        consume_token(db, body.token, 'verify')
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    return {'verified': True}


@router.post('/password/reset/request', status_code=202)
def request_password_reset(body: EmailRequest, request: Request, db=Depends(get_db_connection)):
    from orchestrator_core.core.account_recovery import normalize_email
    try:
        email = normalize_email(body.email)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    public_account_request(request, db, 'reset-request', email)
    user = db.execute('SELECT id,email FROM users WHERE email=? AND active=1', (email,)).fetchone()
    if user:
        deliver_challenge(db, user, 'reset')
    return {'message': 'If this account exists, check your email for a password reset link.'}


@router.post('/password/reset/confirm')
def confirm_password_reset(body: ResetChallenge, request: Request, db=Depends(get_db_connection)):
    from orchestrator_core.core.account_recovery import consume_token
    public_account_request(request, db, 'reset-confirm', identity.digest(body.token))
    try:
        consume_token(db, body.token, 'reset', body.password)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    return {'changed': True, 'sessions_revoked': True}


@router.get('/options')
def account_options():
    return {'registration': get_settings().public_registration}


@router.get('/plans')
def public_plans():
    import os
    from urllib.parse import urlsplit
    from orchestrator_core.core.plans import PLANS
    payment = os.getenv('UPGRADE_PAYMENT_URL', '').strip()
    parsed = urlsplit(payment)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        payment = None
    return {'plans': PLANS, 'payment_url': payment, 'payment_note': 'Plan activation is manual after administrator confirmation of payment. The payment page shows the price and terms.'}
