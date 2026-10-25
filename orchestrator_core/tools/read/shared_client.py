"""
orchestrator_core/tools/read/shared_client.py

Shared, hardened HTTP client for all read-only external tool operations (Section 5.5).
Guarantees:
  1. GET and HEAD methods ONLY. POST, PUT, DELETE, etc. are rejected with SSRFViolationError.
  2. SSRF Guard: Blocks loopback, private IPv4/IPv6, link-local (cloud metadata 169.254.169.254),
     multicast, and non-HTTP schemes.
  3. Domain allowlists enforced per tool spec.
  4. Max payload size capped at 1 MB by default.
  5. Timeout bounds (default 10s).
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from typing import Optional
from urllib.parse import urlparse, urljoin
import time
import urllib3

import requests

from orchestrator_core.exceptions import SSRFViolationError

logger = logging.getLogger(__name__)

DEFAULT_MAX_BYTES = 1024 * 1024  # 1 MB
DEFAULT_TIMEOUT_S = 10.0

# Denylisted host patterns
_DENYLISTED_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
    "instance-data",
}


def _validate_url_ssrf(url: str, allowed_domains: tuple[str, ...] = ()) -> str:
    """Validate that the given URL does not target loopback, private IPs, or cloud metadata."""
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()

    if scheme not in ("http", "https"):
        raise SSRFViolationError(f"Scheme '{scheme}' is not permitted. Only HTTP/HTTPS allowed.")

    if parsed.username or parsed.password:
        raise SSRFViolationError("URL credentials are forbidden")
    if parsed.port not in (None, 80, 443):
        raise SSRFViolationError("Only standard HTTP/HTTPS ports are permitted")
    hostname = parsed.hostname
    if not hostname:
        raise SSRFViolationError(f"URL '{url}' does not contain a valid hostname.")

    hostname_clean = hostname.lower().strip(".")
    if hostname_clean in _DENYLISTED_HOSTS or hostname_clean.endswith(".local") or hostname_clean.endswith(".internal"):
        raise SSRFViolationError(f"Access to host '{hostname}' is blocked by SSRF policy.")

    # Domain allowlist check if specified
    if allowed_domains:
        norm_host = hostname_clean.removeprefix("www.")
        normalized_allowed = {d.lower().strip(".").removeprefix("www.") for d in allowed_domains}
        if norm_host not in normalized_allowed:
            raise SSRFViolationError(
                f"Host '{hostname}' is not on the allowed domain list: {sorted(allowed_domains)}"
            )

    # DNS Resolution and IP validation
    try:
        addr_info = socket.getaddrinfo(hostname, None)
    except socket.gaierror as e:
        raise SSRFViolationError(f"DNS resolution failed for host '{hostname}': {e}") from e

    for item in addr_info:
        ip_str = item[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError as exc:
            raise SSRFViolationError("Invalid DNS address") from exc

        if (
            not ip.is_global
            or ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise SSRFViolationError(
                f"Host '{hostname}' resolved to prohibited address {ip_str} (private, loopback, or link-local)."
            )

    if not addr_info:
        raise SSRFViolationError("DNS returned no usable address")
    addresses = [item[4][0] for item in addr_info]
    return next((addr for addr in addresses if ipaddress.ip_address(addr).version == 4), addresses[0])


def _safe_request(method, url, headers=None, params=None, allowed_domains=(),
                  timeout_s=DEFAULT_TIMEOUT_S, max_bytes=DEFAULT_MAX_BYTES,
                  max_redirects=5, denied_domains=()):
    assert_safe_method(method)
    if not 0 < timeout_s <= 30 or not 0 < max_bytes <= 1048576 or not 0 <= max_redirects <= 5:
        raise SSRFViolationError("Read limits exceed policy")
    current = requests.Request(method, url, params=params).prepare().url
    request_headers = {"User-Agent": "OrchestratorRead/1.0", "Accept-Encoding": "identity"}
    request_headers.update(headers or {})
    deadline = time.monotonic() + timeout_s
    visited = set()
    for hop in range(max_redirects + 1):
        if current in visited:
            raise SSRFViolationError("Redirect loop")
        visited.add(current)
        parsed = urlparse(current)
        host = (parsed.hostname or "").lower().rstrip(".")
        denied = tuple(d.lower().strip(".") for d in denied_domains)
        if any(host == d or host.endswith("." + d) for d in denied):
            raise SSRFViolationError("Host is on the domain denylist")
        address = _validate_url_ssrf(current, tuple(allowed_domains))
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SSRFViolationError("Read deadline exceeded")
        # Connect to the validated numeric address, never resolve the hostname again.
        # TLS still verifies the original hostname and uses it for SNI.
        kwargs = {"host": address, "port": parsed.port or (443 if parsed.scheme == "https" else 80),
                  "timeout": urllib3.Timeout(connect=remaining, read=remaining), "retries": False}
        if parsed.scheme == "https":
            pool = urllib3.HTTPSConnectionPool(**kwargs, server_hostname=host, assert_hostname=host)
        else:
            pool = urllib3.HTTPConnectionPool(**kwargs)
        outgoing = {k: v for k, v in request_headers.items() if k.lower() not in ("host", "connection", "proxy-authorization")}
        outgoing["Host"] = parsed.netloc
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        raw = None
        try:
            raw = pool.urlopen(method, path, headers=outgoing, redirect=False,
                               preload_content=False, decode_content=False)
            if raw.status in (301, 302, 303, 307, 308):
                location = raw.headers.get("Location")
                if not location or hop == max_redirects:
                    raise SSRFViolationError("Redirect limit exceeded or Location missing")
                next_url = urljoin(current, location)
                if urlparse(next_url).netloc != parsed.netloc:
                    request_headers = {k: v for k, v in request_headers.items()
                                       if k.lower() not in ("authorization", "cookie")}
                current = next_url
                continue
            length = raw.headers.get("Content-Length", "")
            if length.isdigit() and int(length) > max_bytes:
                raise SSRFViolationError("Response exceeds maximum size")
            if raw.headers.get("Content-Encoding", "identity").lower() not in ("identity", ""):
                raise SSRFViolationError("Compressed responses are disabled")
            data = bytearray()
            if method != "HEAD":
                while True:
                    if time.monotonic() >= deadline:
                        raise SSRFViolationError("Read deadline exceeded")
                    chunk = raw.read(min(16384, max_bytes + 1 - len(data)), decode_content=False)
                    if not chunk:
                        break
                    data.extend(chunk)
                    if len(data) > max_bytes:
                        raise SSRFViolationError("Response exceeds maximum size")
            response = requests.Response()
            response.status_code = raw.status
            response.headers.update(raw.headers)
            response.url = current
            response._content = bytes(data)
            response.encoding = requests.utils.get_encoding_from_headers(response.headers)
            return response
        finally:
            if raw is not None:
                raw.close()
            pool.close()
    raise SSRFViolationError("Redirect limit exceeded")


def safe_get(url: str, headers=None, params=None, allowed_domains=(),
             timeout_s=DEFAULT_TIMEOUT_S, max_bytes=DEFAULT_MAX_BYTES,
             max_redirects=5, denied_domains=()) -> requests.Response:
    return _safe_request("GET", url, headers, params, allowed_domains, timeout_s,
                         max_bytes, max_redirects, denied_domains)


def safe_head(url: str, headers=None, allowed_domains=(),
              timeout_s=DEFAULT_TIMEOUT_S) -> requests.Response:
    return _safe_request("HEAD", url, headers=headers, allowed_domains=allowed_domains,
                         timeout_s=timeout_s)


def assert_safe_method(method: str) -> None:
    """Ensure HTTP method is GET or HEAD only."""
    upper = method.upper().strip()
    if upper not in ("GET", "HEAD"):
        raise SSRFViolationError(f"HTTP method '{upper}' is strictly forbidden on read tools. Only GET/HEAD allowed.")
