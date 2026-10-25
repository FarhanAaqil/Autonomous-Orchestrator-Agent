import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import ValidationError
from orchestrator_core.config import Settings, get_settings
from orchestrator_core.dependencies import verify_bearer_token
from orchestrator_core.main import app


@pytest.mark.parametrize("values", [
    {"auth_token": None}, {"auth_token": "short"},
    {"executor_hmac_secret": "aaqil-secret-hmac-key-dev-environment"},
    {"allow_insecure_local": True},
])
def test_production_rejects_insecure_configuration(values):
    defaults = dict(environment="production", auth_token="a-private-token-with-at-least-32-characters",
                    executor_hmac_secret="independent-secret-with-randomness-0123456789",
                    allow_insecure_local=False, _env_file=None)
    defaults.update(values)
    with pytest.raises(ValidationError):
        Settings(**defaults)


def test_local_auth_bypass_requires_explicit_opt_in():
    with pytest.raises(ValidationError):
        Settings(auth_token=None, allow_insecure_local=False, _env_file=None)


def test_circuit_reset_requires_auth():
    app.dependency_overrides[get_settings] = lambda: Settings(auth_token="test-auth", _env_file=None)
    try:
        with TestClient(app) as client:
            assert client.post("/system/circuit/reset").status_code == 401
            assert client.get("/system/circuit").status_code == 401
            assert client.get("/health").status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_route_inventory_has_explicit_auth_boundary():
    public = {"/health", "/", "/ui"}
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path not in public:
            assert any(d.call is verify_bearer_token for d in route.dependant.dependencies), route.path
