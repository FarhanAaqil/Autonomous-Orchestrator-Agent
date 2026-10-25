"""One admission policy for all execution entry points; context is server-owned."""
from contextlib import contextmanager
from contextvars import ContextVar
from orchestrator_core.core.action_catalog import ACTION_CATALOG, ACTION_ALIASES
from orchestrator_core.models import canonical_agent_name
from orchestrator_core.exceptions import AgentDisabledError, KillSwitchActiveError, SecurityPolicyViolationError

execution_origin = ContextVar("execution_origin", default=("orchestrator", None))


def require_execution(db, agent="orchestrator", action_type=None):
    canonical = canonical_agent_name(agent)
    flags = {r["key"]: r["value"].strip().lower() for r in db.execute("SELECT key,value FROM system_flags")}
    if flags.get("kill_switch") in {"on", "true", "1"}:
        raise KillSwitchActiveError("Execution is paused by the emergency kill switch")
    if any(flags.get(f"agent_enabled_{a}") in {"0", "false", "off"} for a in (canonical, agent)):
        raise AgentDisabledError(canonical)
    if action_type:
        name = ACTION_ALIASES.get(action_type, action_type)
        spec = ACTION_CATALOG.get(name)
        if spec is None or canonical not in spec.agents:
            raise SecurityPolicyViolationError(f"Agent {canonical} cannot propose {name}")


@contextmanager
def execution_scope(agent, session_id=None):
    token = execution_origin.set((canonical_agent_name(agent), session_id))
    try:
        yield
    finally:
        execution_origin.reset(token)


def run_handler(handler, command, db, agent, metadata=None, session_id=None):
    require_execution(db, agent)
    with execution_scope(agent, session_id):
        return handler(command, metadata=metadata or {})
