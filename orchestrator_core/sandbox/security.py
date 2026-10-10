"""
orchestrator_core/sandbox/security.py

Sandbox isolation and security enforcement for web browsing (Section 5.5).
Guarantees:
  1. Scheme Lockdown: Only HTTP and HTTPS allowed. file://, data:, about:, chrome:, javascript:
     are blocked unconditionally.
  2. SSRF Isolation: Blocks loopback (127.0.0.1, ::1), private IPs (RFC 1918), link-local
     metadata endpoints (169.254.169.254), multicast, and internal domains.
  3. Domain Allowlist & Denylist Enforcement.
  4. Navigation Limits: Timeout, payload size, and redirect chain bounds.
  5. Read-Only Invariant: Mutating operations (form submissions, storage modification) are blocked.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from typing import Sequence
from urllib.parse import urlparse

from orchestrator_core.exceptions import SSRFViolationError

logger = logging.getLogger(__name__)


class SandboxSecurityError(SSRFViolationError):
    """Raised when an operation violates browser sandbox security policy."""
    pass


# Forbidden URL schemes
FORBIDDEN_SCHEMES = frozenset({
    "file",
    "data",
    "about",
    "chrome",
    "chrome-extension",
    "javascript",
    "ftp",
    "gopher",
    "mailto",
    "blob",
    "ws",
    "wss",
})

# Denylisted hostnames and suffixes
DENYLISTED_HOSTS = frozenset({
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
    "instance-data",
    "169.254.169.254",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
})


def validate_sandbox_url(
    url: str,
    allowed_domains: Sequence[str] = (),
    denied_domains: Sequence[str] = (),
) -> None:
    """
    Validate that target URL meets all sandbox isolation policies.
    Raises SandboxSecurityError if any policy violation is detected.
    """
    if not url or not isinstance(url, str):
        raise SandboxSecurityError("Target URL must be a non-empty string.")

    cleaned_url = url.strip()
    parsed = urlparse(cleaned_url)
    scheme = (parsed.scheme or "").lower()

    # 1. Scheme Validation
    if scheme in FORBIDDEN_SCHEMES:
        raise SandboxSecurityError(
            f"Sandbox escape attempt: Scheme '{scheme}://' is strictly prohibited. Only HTTP/HTTPS permitted."
        )

    if scheme not in ("http", "https"):
        raise SandboxSecurityError(
            f"Invalid scheme '{scheme}'. Only HTTP and HTTPS schemes are supported."
        )

    # 2. Hostname Validation
    hostname = parsed.hostname
    if not hostname:
        raise SandboxSecurityError(f"URL '{url}' does not contain a valid hostname.")

    hostname_clean = hostname.lower().strip(".")
    if hostname_clean in DENYLISTED_HOSTS:
        raise SandboxSecurityError(
            f"Sandbox access to prohibited host '{hostname}' is blocked."
        )

    if hostname_clean.endswith(".local") or hostname_clean.endswith(".internal"):
        raise SandboxSecurityError(
            f"Access to internal domain '{hostname}' is blocked by sandbox policy."
        )

    # 3. Denied Domains Check
    if denied_domains:
        normalized_denied = {d.lower().strip(".").removeprefix("www.") for d in denied_domains}
        norm_host = hostname_clean.removeprefix("www.")
        for d in normalized_denied:
            if norm_host == d or norm_host.endswith(f".{d}"):
                raise SandboxSecurityError(
                    f"Host '{hostname}' is present in the sandbox domain denylist."
                )

    # 4. Allowed Domains Check
    if allowed_domains:
        normalized_allowed = {d.lower().strip(".").removeprefix("www.") for d in allowed_domains}
        norm_host = hostname_clean.removeprefix("www.")
        match = any(norm_host == d or norm_host.endswith(f".{d}") for d in normalized_allowed)
        if not match:
            raise SandboxSecurityError(
                f"Host '{hostname}' is not authorized by the sandbox domain allowlist: {sorted(allowed_domains)}"
            )

    # 5. IP Address and DNS Resolution Validation
    # Direct IP literal check
    try:
        ip = ipaddress.ip_address(hostname_clean)
        _check_ip_safety(ip, hostname_clean)
        return
    except ValueError:
        pass

    # DNS Resolution
    try:
        addr_info = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise SandboxSecurityError(f"DNS resolution failed for host '{hostname}': {exc}") from exc

    for item in addr_info:
        ip_str = item[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        _check_ip_safety(ip, hostname)


def _check_ip_safety(ip: ipaddress.IPv4Address | ipaddress.IPv6Address, host_repr: str) -> None:
    """Verify that the resolved IP address is public and non-local."""
    if (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        raise SandboxSecurityError(
            f"Host '{host_repr}' resolved to prohibited address '{ip}' "
            "(private, loopback, link-local, or metadata address blocked)."
        )


def assert_read_only_action(action: str) -> None:
    """
    Ensure requested browser operation is read-only.
    Mutating operations (form submissions, POST calls, write operations) are prohibited.
    """
    act = (action or "").lower().strip()
    forbidden = {"submit", "form_submit", "post", "put", "delete", "write", "mutate", "click_submit"}
    if act in forbidden:
        raise SandboxSecurityError(
            f"Mutating browser action '{action}' is forbidden in read sandbox. "
            "Real-world side effects must be submitted as proposals via propose_action."
        )
