import base64
import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from orchestrator_core.exceptions import SSRFViolationError
from orchestrator_core.sandbox.client import SandboxBrowserClient
from orchestrator_core.sandbox.security import SandboxSecurityError
from orchestrator_core.tools.read import shared_client as http


def raw(status=200, headers=None, body=b"ok"):
    response = Mock()
    response.status = status
    response.headers = headers or {}
    stream = io.BytesIO(body)
    response.read.side_effect = lambda size, **kwargs: stream.read(size)
    return response


def test_dns_is_pinned_and_tls_keeps_original_hostname():
    public = [(2, 1, 6, "", ("93.184.216.34", 443))]
    private = [(2, 1, 6, "", ("127.0.0.1", 443))]
    with patch.object(http.socket, "getaddrinfo", side_effect=[public, private]) as dns, patch.object(
        http.urllib3, "HTTPSConnectionPool"
    ) as pool:
        pool.return_value.urlopen.return_value = raw()
        assert http.safe_get("https://example.org/path").content == b"ok"
        assert dns.call_count == 1
        assert pool.call_args.kwargs["host"] == "93.184.216.34"
        assert pool.call_args.kwargs["assert_hostname"] == "example.org"
        assert pool.call_args.kwargs["server_hostname"] == "example.org"


@pytest.mark.parametrize("location", ["/again", "../again", "https://other.example.org/again"])
def test_redirects_are_bounded_and_connections_close(location):
    responses = [raw(302, {"Location": location}) for _ in range(6)]
    with patch.object(http, "_validate_url_ssrf", return_value="93.184.216.34"), patch.object(
        http.urllib3, "HTTPSConnectionPool"
    ) as pool:
        pool.return_value.urlopen.side_effect = responses
        with pytest.raises(SSRFViolationError, match="Redirect"):
            http.safe_get("https://example.org/start", max_redirects=2)
        assert pool.return_value.urlopen.call_count <= 3
        assert pool.return_value.close.call_count == pool.return_value.urlopen.call_count


def test_redirect_to_private_address_stops_before_second_connection():
    with patch.object(http, "_validate_url_ssrf", side_effect=["93.184.216.34", SSRFViolationError("private")]), patch.object(
        http.urllib3, "HTTPSConnectionPool"
    ) as pool:
        pool.return_value.urlopen.return_value = raw(302, {"Location": "http://127.0.0.1/"})
        with pytest.raises(SSRFViolationError):
            http.safe_get("https://example.org/")
        assert pool.call_count == 1


@pytest.mark.parametrize("error", [SandboxSecurityError("policy rejection"), ConnectionError("offline")])
def test_remote_failure_never_falls_back(error):
    client = SandboxBrowserClient(rpc_url="http://sandbox:8888")
    with patch("orchestrator_core.sandbox.client.validate_sandbox_url"), patch.object(
        client, "_browse_rpc", side_effect=error
    ), patch.object(client, "_browse_local") as local:
        with pytest.raises(type(error)):
            client.browse("https://example.org")
        local.assert_not_called()


def test_missing_required_sandbox_is_an_error(monkeypatch):
    monkeypatch.delenv("SANDBOX_BROWSER_URL", raising=False)
    monkeypatch.delenv("SANDBOX_ALLOW_LOCAL", raising=False)
    with patch("orchestrator_core.sandbox.client.validate_sandbox_url"):
        with pytest.raises(SandboxSecurityError, match="not configured"):
            SandboxBrowserClient().browse("https://example.org")


def boundary_module():
    path = Path(__file__).resolve().parents[1] / "docker/browser_sandbox/gateway.py"
    spec = importlib.util.spec_from_file_location("sandbox_gateway_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH"])
def test_browser_mutations_are_aborted_and_logged(method, caplog):
    module = boundary_module()
    req = SimpleNamespace(url="https://example.org", timeout_ms=1000, max_bytes=1024,
                          allowed_domains=[], denied_domains=[])
    route = Mock()
    route.request.method = method
    with patch.object(module.requests, "post") as gateway:
        module.ReadBoundary(req).handle(route)
    route.abort.assert_called_once_with("accessdenied")
    gateway.assert_not_called()
    assert "Mutating browser method blocked" in caplog.text


def test_browser_reads_only_use_gateway_fulfillment():
    module = boundary_module()
    req = SimpleNamespace(url="https://example.org", timeout_ms=1000, max_bytes=1024,
                          allowed_domains=[], denied_domains=[])
    route = Mock()
    route.request.method = "GET"
    route.request.url = req.url
    response = Mock()
    response.json.return_value = {"url": req.url, "status": 200, "content_type": "text/html",
                                 "body": base64.b64encode(b"<p>Hello</p>").decode()}
    with patch.object(module.requests, "post", return_value=response) as gateway:
        module.ReadBoundary(req).handle(route)
    assert gateway.call_args.args[0] == module.EGRESS_URL
    route.fulfill.assert_called_once()
    route.continue_.assert_not_called()


def test_browser_configuration_blocks_page_scripts_and_workers():
    root = Path(__file__).resolve().parents[1]
    server = (root / "docker/browser_sandbox/server.py").read_text()
    assert 'java_script_enabled=False' in server
    assert 'service_workers="block"' in server
    assert 'accept_downloads=False' in server
    assert 'context.route("**/*", boundary.handle)' in server
    firewall = (root / "docker/browser_sandbox/entrypoint.sh").read_text()
    assert "iptables -P OUTPUT DROP" in firewall
    assert "ip6tables -P OUTPUT DROP" in firewall
    assert "--bounding-set=-all" in firewall
