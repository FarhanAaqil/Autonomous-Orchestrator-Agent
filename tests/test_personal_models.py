from types import SimpleNamespace
import json
from cryptography.fernet import Fernet
from orchestrator_core.core.identity import create_user
from orchestrator_core.core.policy import execution_scope
from orchestrator_core.core.connections import store_connection
from orchestrator_core.core.usage import usage_db


def test_personal_model_key_never_bills_operator(db, monkeypatch):
    from orchestrator_core.core.provider import Groq
    owner = create_user(db, 'personal', 'fixture-password-123')['id']
    monkeypatch.setenv('CONNECTION_KEYS', json.dumps({'one': Fernet.generate_key().decode()}))
    monkeypatch.setenv('CONNECTION_ACTIVE_KEY', 'one')
    store_connection(db, owner, 'groq', {'access_token': 'personal-fixture-key'}, [])
    used = []
    class Client:
        def __init__(self, **kwargs):
            used.append(kwargs['api_key'])
            self.chat = self.completions = self
        def create(self, **kwargs):
            return SimpleNamespace(usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5))
    monkeypatch.setattr('orchestrator_core.core.provider.SDKGroq', Client)
    marker = usage_db.set(db)
    try:
        with execution_scope('orchestrator', owner=owner):
            Groq(api_key='operator-fixture-key').create(messages=[], max_tokens=10)
    finally:
        usage_db.reset(marker)
    assert used == ['personal-fixture-key']
    row = db.execute('SELECT * FROM provider_usage').fetchone()
    assert row['user_id'] == owner and row['personal_key'] == 1
    assert row['reserved_cost'] == 0 and row['cost_usd'] == 0


def test_router_cache_does_not_cross_accounts(monkeypatch):
    from orchestrator_core.core import router
    calls = []
    def classify(command, **kwargs):
        calls.append(command)
        return {'agent': 'general_chat_agent', 'confidence': 0.99, 'reasoning': 'fixture'}
    monkeypatch.setattr(router, '_call_groq', classify)
    router.clear_router_cache()
    for owner in ('alice', 'alice', 'bob'):
        with execution_scope('orchestrator', owner=owner):
            router.classify('same private query')
    assert len(calls) == 2
    router.clear_router_cache()


def test_bounded_provider_thread_preserves_owner():
    from orchestrator_core.core.provider import bounded_call
    from orchestrator_core.core.ownership import execution_owner
    with execution_scope('orchestrator', owner='alice'):
        assert bounded_call(execution_owner.get) == 'alice'
