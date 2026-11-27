"""Server-owned plan policy; expiry is checked on each access."""
from datetime import datetime, timezone, timedelta
from orchestrator_core.storage.db import log_audit

PLANS = {
    'free': {'runs_per_day': 10, 'active_schedules': 1, 'connected_accounts': 2, 'daily_tokens': 20000, 'monthly_tokens': 300000, 'concurrent_runs': 1, 'emails_per_day': 10},
    'pro': {'runs_per_day': 100, 'active_schedules': 10, 'connected_accounts': 8, 'daily_tokens': 200000, 'monthly_tokens': 3000000, 'concurrent_runs': 3, 'emails_per_day': 100},
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


class PlanLimitExceeded(ValueError):
    pass


def require_capacity(db, user_id, resource, used, requested=1):
    if user_id is None:
        return  # Local legacy workspace, never a public account.
    limit = account_plan(db, user_id)['limits'][resource]
    if used + requested > limit:
        raise PlanLimitExceeded(f'Your plan allows {limit} {resource.replace("_", " ")}')


def require_job_capacity(db, user_id):
    if user_id is None:
        return
    day = datetime.now(timezone.utc).date().isoformat()
    used = run_count(db, user_id, day)
    require_capacity(db, user_id, 'runs_per_day', used)
    require_new_account_capacity(db, user_id)


def run_count(db, user_id, period):
    jobs = db.execute('SELECT COUNT(*) FROM jobs WHERE user_id=? AND substr(created_at,1,?)=?', (user_id, len(period), period)).fetchone()[0]
    synchronous = db.execute("SELECT COUNT(*) FROM audit_log WHERE actor=? AND event='synchronous_run_started' AND substr(created_at,1,?)=?", (user_id, len(period), period)).fetchone()[0]
    return jobs + synchronous


def require_new_account_capacity(db, user_id):
    at = datetime.now(timezone.utc)
    row = db.execute('SELECT created_at FROM users WHERE id=? AND active=1', (user_id,)).fetchone()
    if not row:
        raise PlanLimitExceeded('Account unavailable')
    created = datetime.fromisoformat(row['created_at'])
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    if at - created >= timedelta(hours=24):
        return
    since = (at - timedelta(hours=1)).isoformat()
    used = db.execute('SELECT COUNT(*) FROM jobs WHERE user_id=? AND created_at>=?', (user_id, since)).fetchone()[0]
    used += db.execute("SELECT COUNT(*) FROM audit_log WHERE actor=? AND event='synchronous_run_started' AND created_at>=?", (user_id, since)).fetchone()[0]
    if used >= 10:
        raise PlanLimitExceeded('New accounts allow 10 run attempts per hour during their first 24 hours; retry later')


def reserve_synchronous_run(db, user_id, path):
    if user_id is None:
        return
    from orchestrator_core.storage.transactions import transaction
    with transaction(db):
        require_job_capacity(db, user_id)
        log_audit(db, user_id, 'synchronous_run_started', 'request', detail={'path': path})


def can_claim(db, user_id):
    if user_id is None:
        return True
    user = db.execute('SELECT * FROM users WHERE id=? AND active=1', (user_id,)).fetchone()
    if not user:
        return False
    used = db.execute("SELECT COUNT(*) FROM jobs WHERE user_id=? AND status='running'", (user_id,)).fetchone()[0]
    return used < PLANS[effective_plan(user)]['concurrent_runs']


def require_schedule_capacity(db, user_id, excluding=None):
    if user_id is None:
        return
    used = db.execute('SELECT COUNT(*) FROM schedules WHERE user_id=? AND is_active=1 AND id<>?', (user_id, excluding or '')).fetchone()[0]
    require_capacity(db, user_id, 'active_schedules', used)


def usage_summary(db, user_id):
    day = datetime.now(timezone.utc).date().isoformat()
    if getattr(db, 'dialect', None) == 'postgresql':
        return db.execute('SELECT public.account_usage_summary(?,?)', (user_id, day)).fetchone()[0]
    return {
        'day_utc': day,
        'month_utc': day[:7],
        'monthly_runs': run_count(db, user_id, day[:7]),
        'monthly_tokens': db.execute('SELECT COALESCE(SUM(COALESCE(tokens_in+tokens_out,reserved_tokens)),0) FROM provider_usage WHERE user_id=? AND substr(used_at,1,7)=?', (user_id, day[:7])).fetchone()[0],
        'runs': run_count(db, user_id, day),
        'tokens': db.execute('SELECT COALESCE(SUM(COALESCE(tokens_in+tokens_out,reserved_tokens)),0) FROM provider_usage WHERE user_id=? AND substr(used_at,1,10)=?', (user_id, day)).fetchone()[0],
        'active_schedules': db.execute('SELECT COUNT(*) FROM schedules WHERE user_id=? AND is_active=1', (user_id,)).fetchone()[0],
        'connected_accounts': db.execute('SELECT COUNT(*) FROM connections WHERE user_id=?', (user_id,)).fetchone()[0],
    }
