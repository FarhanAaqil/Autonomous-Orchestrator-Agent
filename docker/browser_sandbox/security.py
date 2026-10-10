"""
docker/browser_sandbox/security.py

Sandbox URL and SSRF validation for container runtime.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from typing import Sequence
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class SandboxSecurityError(Exception):
    """Raised when an operation violates browser sandbox security policy."""
    pass


FORBIDDEN_SCHEMES = frozenset({
    "file", "data", "about", "chrome", "chrome-extension",
    "javascript", "ftp", "gopher", "mailto", "blob", "ws", "wss",
})

DENYLISTED_HOSTS = frozenset({
    "localhost", "localhost.localdomain", "metadata.google.internal",
    "instance-data", "169.254.169.254", "127.0.0.1", "0.0.0.0", "::1",
})


def validate_sandbox_url(
    url: str,
    allowed_domains: Sequence[str] = (),
    denied_domains: Sequence[str] = (),
) -> None:
    if not url or not isinstance(url, str):
        raise SandboxSecurityError("Target URL must be a non-empty string.")

    cleaned_url = url.strip()
    parsed = urlparse(cleaned_url)
    scheme = (parsed.scheme or "").lower()

    if scheme in FORBIDDEN_SCHEMES:
        raise SandboxSecurityError(f"Scheme '{scheme}://' is prohibited in the sandbox.")

    if scheme not in ("http", "https"):
        raise SandboxSecurityError(f"Scheme '{scheme}' is not supported. Only HTTP and HTTPS allowed.")

    hostname = parsed.hostname
    if not hostname:
        raise SandboxSecurityError(f"URL '{url}' does not contain a valid hostname.")

    hostname_clean = hostname.lower().strip(".")
    if hostname_clean in DENYLISTED_HOSTS:
        raise SandboxSecurityError(f"Sandbox access to host '{hostname}' is blocked.")

    if hostname_clean.endswith(".local") or hostname_clean.endswith(".internal"):
        raise SandboxSecurityError(f"Access to internal domain '{hostname}' is blocked.")

    if denied_domains:
        normalized_denied = {d.lower().strip(".").removeprefix("www.") for d in denied_domains}
        norm_host = hostname_clean.removeprefix("www.")
        for d in normalized_denied:
            if norm_host == d or norm_host.endswith(f".{d}"):
                raise SandboxSecurityError(f"Host '{hostname}' is on the domain denylist.")

    if allowed_domains:
        normalized_allowed = {d.lower().strip(".").removeprefix("www.") for d in allowed_domains}
        norm_host = hostname_clean.removeprefix("www.")
        match = any(norm_host == d or norm_host.endswith(f".{d}") for d in normalized_allowed)
        if not match:
            raise SandboxSecurityError(f"Host '{hostname}' is not authorized by the allowlist: {sorted(allowed_domains)}")

    # Check IP literal or resolve via DNS
    try:
        ip = ipaddress.ip_address(hostname_clean)
        _check_ip_safety(ip, hostname_clean)
        return
    except ValueError:
        pass

    try:
        addr_info = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise SandboxSecurityError(f"DNS resolution failed for '{hostname}': {exc}") from exc

    for item in addr_info:
        ip_str = item[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        _check_ip_safety(ip, hostname)


def _check_ip_safety(ip: ipaddress.IPv4Address | ipaddress.IPv6Address, host_repr: str) -> None:
    if (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        raise SandboxSecurityError(f"Host '{host_repr}' resolved to prohibited address '{ip}'.")
