"""Atomic conservative spend reservations shared by every model entry point."""
import json
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone

from orchestrator_core.exceptions import BudgetExceededError, TokenBudgetExceededError
from orchestrator_core.jobs.leases import current_lease, require_lease

usage_db = ContextVar('usage_db', default=None)
reference_context = ContextVar('reference_context', default='')
# Conservative configured accounting ceilings, not a claim about provider prices.
INPUT_PER_MILLION = 10.0
OUTPUT_PER_MILLION = 30.0


def reserve(db, messages, output_limit):
    prompt = len(json.dumps(messages, ensure_ascii=False).encode('utf-8')) + 256
    output_limit = min(int(output_limit), 4096)
    timestamp = datetime.now(timezone.utc).isoformat()
    lease = current_lease.get()
    reservation = str(uuid.uuid4())
    db.execute('BEGIN IMMEDIATE')
    try:
        if lease:
            require_lease(db)
            job = db.execute('SELECT * FROM jobs WHERE id=?', (lease[0],)).fetchone()
            spent = db.execute('SELECT COALESCE(SUM(COALESCE(tokens_in+tokens_out,reserved_tokens)),0) FROM provider_usage WHERE job_id=?', (lease[0],)).fetchone()[0]
            remaining = job['token_budget'] - max(spent, job['tokens_used']) - prompt
            if remaining <= 0:
                raise TokenBudgetExceededError(job['id'], prompt+spent, job['token_budget'])
            output_limit = min(output_limit, remaining)
        cost = (prompt * INPUT_PER_MILLION + output_limit * OUTPUT_PER_MILLION) / 1_000_000
        limit_row = db.execute("SELECT value FROM system_flags WHERE key='daily_budget_usd'").fetchone()
        limit = float(limit_row[0]) if limit_row else 5.0
        spent = db.execute('SELECT COALESCE(SUM(COALESCE(cost_usd,reserved_cost)),0) FROM provider_usage WHERE substr(used_at,1,10)=?', (timestamp[:10],)).fetchone()[0]
        if spent + cost > limit:
            raise BudgetExceededError(spent+cost, limit)
        db.execute('INSERT INTO provider_usage (id,job_id,used_at,reserved_tokens,reserved_cost,state) VALUES (?,?,?,?,?,?)',
                   (reservation, lease[0] if lease else None, timestamp, prompt+output_limit, cost, 'reserved'))
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return reservation, output_limit


def settle(db, reservation, usage):
    # Missing usage or an interrupted call keeps the full reservation charged.
    if usage is None:
        return
    incoming, outgoing = usage.prompt_tokens, usage.completion_tokens
    cost = (incoming*INPUT_PER_MILLION + outgoing*OUTPUT_PER_MILLION) / 1_000_000
    with db:
        db.execute("UPDATE provider_usage SET tokens_in=?,tokens_out=?,cost_usd=?,state='reported' WHERE id=? AND state='reserved'",
                   (incoming, outgoing, cost, reservation))
