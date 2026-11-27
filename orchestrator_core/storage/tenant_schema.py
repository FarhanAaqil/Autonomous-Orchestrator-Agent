"""PostgreSQL tenant boundaries; run only with the migration role."""
from orchestrator_core.core.ownership import OWNED_TABLES

TENANT_TABLES = OWNED_TABLES + ('connections', 'oauth_states')


def install(db):
    owner = db.execute("SELECT id FROM users WHERE role='administrator' ORDER BY created_at,id LIMIT 1").fetchone()
    for table in TENANT_TABLES:
        missing = db.execute(f'SELECT COUNT(*) FROM {table} WHERE user_id IS NULL').fetchone()[0]
        if missing:
            if not owner:
                raise RuntimeError('Create the first administrator before migrating legacy workspace data')
            db.execute(f'UPDATE {table} SET user_id=? WHERE user_id IS NULL', (owner['id'],))
        db.execute(f'ALTER TABLE {table} ALTER COLUMN user_id SET NOT NULL')
        db.execute(f"ALTER TABLE {table} ALTER COLUMN user_id SET DEFAULT NULLIF(current_setting('app.user_id',true),'')")
        db.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
        db.execute(f"CREATE POLICY account_owner ON {table} USING (user_id=NULLIF(current_setting('app.user_id',true),'')) WITH CHECK (user_id=NULLIF(current_setting('app.user_id',true),''))")
    # The table-owning migrator bypasses policies. Runtime roles must never own
    # these tables or have BYPASSRLS. Only aggregate values cross tenant scopes.
    db.execute("""CREATE FUNCTION public.platform_daily_spend(day_value text) RETURNS double precision
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public SET row_security=off
        AS $$ SELECT COALESCE(SUM(COALESCE(cost_usd,reserved_cost)),0)::double precision
        FROM public.provider_usage WHERE substr(used_at,1,10)=day_value $$""")
    db.execute("""CREATE FUNCTION public.account_usage_summary(target_owner text, day_value text) RETURNS json
        LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,public SET row_security=off
        AS $$ BEGIN
          IF NOT EXISTS (SELECT 1 FROM public.users WHERE id=NULLIF(current_setting('app.user_id',true),'') AND active=1 AND (id=target_owner OR role='administrator')) THEN
            RAISE EXCEPTION 'Account usage unavailable' USING ERRCODE='42501';
          END IF;
          RETURN json_build_object(
            'day_utc',day_value,'month_utc',substr(day_value,1,7),
            'runs',(SELECT COUNT(*) FROM public.jobs WHERE user_id=target_owner AND substr(created_at,1,10)=day_value),
            'monthly_runs',(SELECT COUNT(*) FROM public.jobs WHERE user_id=target_owner AND substr(created_at,1,7)=substr(day_value,1,7)),
            'tokens',(SELECT COALESCE(SUM(COALESCE(tokens_in+tokens_out,reserved_tokens)),0) FROM public.provider_usage WHERE user_id=target_owner AND substr(used_at,1,10)=day_value),
            'monthly_tokens',(SELECT COALESCE(SUM(COALESCE(tokens_in+tokens_out,reserved_tokens)),0) FROM public.provider_usage WHERE user_id=target_owner AND substr(used_at,1,7)=substr(day_value,1,7)),
            'active_schedules',(SELECT COUNT(*) FROM public.schedules WHERE user_id=target_owner AND is_active=1),
            'connected_accounts',(SELECT COUNT(*) FROM public.connections WHERE user_id=target_owner));
        END $$""")
