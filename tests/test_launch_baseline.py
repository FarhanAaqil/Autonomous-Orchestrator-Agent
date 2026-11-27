from pathlib import Path
from orchestrator_core.config import Settings
from orchestrator_core.version import VERSION

ROOT = Path(__file__).resolve().parents[1]


def test_version_has_one_source(monkeypatch):
    monkeypatch.setenv('APP_VERSION', 'obsolete-version')
    assert Settings().app_version == VERSION


def test_proxy_matches_runtime_and_requires_explicit_public_profile():
    import yaml
    config = yaml.safe_load((ROOT / 'docker-compose.yml').read_text())
    assert config['services']['caddy']['profiles'] == ['public']
    assert 'orchestrator_core:8080' in (ROOT / 'Caddyfile').read_text()
    assert config['services']['orchestrator_core']['ports'] == ['127.0.0.1:8080:8080']
