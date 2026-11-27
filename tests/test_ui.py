"""HTTP checks for compiled delivery; interactive workflows live in Playwright."""
import re
import pytest
from fastapi.testclient import TestClient
from orchestrator_core.main import app


@pytest.mark.parametrize('path', ['/', '/ui'])
def test_compiled_entry_is_local_and_has_security_headers(path):
    response = TestClient(app).get(path)
    assert response.status_code == 200
    assert '<div id="root"></div>' in response.text
    assert 'https://' not in response.text
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert "script-src 'self'" in response.headers['content-security-policy']
    assets = re.findall(r'(?:src|href)="(/assets/[^"]+)"', response.text)
    assert assets
    for asset in assets:
        assert TestClient(app).get(asset).status_code == 200


@pytest.mark.parametrize('path', ['/static/package.json', '/static/src/App.tsx', '/assets/../package.json'])
def test_source_is_not_exposed(path):
    assert TestClient(app).get(path).status_code == 404
