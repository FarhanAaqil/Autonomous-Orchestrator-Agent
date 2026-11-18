"""Server-owned plan policy; expiry is checked on each access."""
from datetime import datetime, timezone
from orchestrator_core.storage.db import log_audit

PLANS = {
    'free': {'runs_per_day': 10, 'active_schedules': 1, 'connected_accounts': 2, 'daily_tokens': 20000, 'concurrent_runs': 1, 'emails_per_day': 10},
    'pro': {'runs_per_day': 100, 'active_schedules': 10, 'connected_accounts': 8, 'daily_tokens': 200000, 'concurrent_runs': 3, 'emails_per_day': 100},
}


def effective_plan(user, at=None):
    at = at or datetime.now(timezone.utc)
    if user['plan'] == 'pro' and user['paid_until']:
        try:
            expiry = datetime.fromisoformat(user['paid_until'])
            if expiry.tzinfo and expiry > at:
                return 'pro'
        except ValueError:
            pass
    return 'free'


def account_plan(db, user_id):
    user = db.execute('SELECT plan,paid_until FROM users WHERE id=? AND active=1', (user_id,)).fetchone()
    if not user:
        raise ValueError('Account not found')
    plan = effective_plan(user)
    return {'plan': plan, 'paid_until': user['paid_until'], 'expired': user['plan'] == 'pro' and plan == 'free', 'limits': dict(PLANS[plan])}


def grant_plan(db, actor_id, user_id, plan, paid_until=None):
    actor = db.execute("SELECT 1 FROM users WHERE id=? AND active=1 AND role='administrator'", (actor_id,)).fetchone()
    if not actor:
        raise PermissionError('Administrator required')
    if plan not in PLANS:
        raise ValueError('Unknown plan')
    if plan == 'pro':
        try:
            expiry = datetime.fromisoformat(paid_until or '')
            if not expiry.tzinfo or expiry <= datetime.now(timezone.utc):
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError('A future timezone-aware expiry is required') from None
        paid_until = expiry.astimezone(timezone.utc).isoformat()
    else:
        paid_until = None
    with db:
        changed = db.execute('UPDATE users SET plan=?,paid_until=? WHERE id=?', (plan, paid_until, user_id))
        if changed.rowcount != 1:
            raise ValueError('Account not found')
        log_audit(db, actor_id, 'plan_changed', 'user', user_id, {'plan': plan, 'paid_until': paid_until})
