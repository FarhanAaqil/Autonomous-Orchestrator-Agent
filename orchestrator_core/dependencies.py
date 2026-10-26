"""Session and service authentication, with centralized role and CSRF checks."""
import secrets
from typing import Optional

from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from orchestrator_core.config import Settings, get_settings
from orchestrator_core.storage.db import get_db_connection

security = HTTPBearer(auto_error=False)


def verify_bearer_token(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
    settings: Settings = Depends(get_settings),
    db=Depends(get_db_connection),
):
    from orchestrator_core.core.identity import principal, csrf_token
    token = request.cookies.get('orchestrator_session')
    user = None
    if token:
        user = principal(db, token)
        if not user:
            raise HTTPException(401, 'Session expired or revoked')
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            supplied = request.headers.get('x-csrf-token', '')
            if not secrets.compare_digest(supplied, csrf_token(token)):
                raise HTTPException(403, 'CSRF verification failed')
    elif credentials and settings.auth_token and secrets.compare_digest(credentials.credentials, settings.auth_token):
        user = {'id': 'service', 'username': 'service', 'role': 'administrator'}
    elif settings.allow_insecure_local and settings.environment == 'development' and not settings.auth_token:
        user = {'id': 'local-development', 'username': 'local-development', 'role': 'administrator'}
    if not user:
        raise HTTPException(401, 'Authentication required', headers={'WWW-Authenticate': 'Bearer'})
    mutation = request.method not in ('GET', 'HEAD', 'OPTIONS')
    admin_path = request.url.path.startswith(('/system/', '/auth/users', '/agents/'))
    if mutation and request.url.path not in ('/auth/logout', '/auth/password') and (user['role'] == 'viewer' or (admin_path and user['role'] != 'administrator')):
        raise HTTPException(403, 'This operation requires a higher role')
    request.state.principal = user
    return user['id']
