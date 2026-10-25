"""
orchestrator_core/sandbox/client.py

Client interface for the isolated browser sandbox.
Dispatches requests to the Dockerized browser RPC container when SANDBOX_BROWSER_URL
is set, or uses the local ephemeral Playwright/HTTP driver with identical safety boundaries.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Optional, Sequence
from urllib.parse import urlparse

import requests

from orchestrator_core.sandbox.security import (
    SandboxSecurityError,
    validate_sandbox_url,
)
from orchestrator_core.sandbox.types import (
    BrowseRequest,
    BrowseResponse,
    NavigationLimits,
)

logger = logging.getLogger(__name__)

# Environment variable to target Docker sandbox container
SANDBOX_BROWSER_URL_ENV = "SANDBOX_BROWSER_URL"


class SandboxBrowserClient:
    """
    Client for interacting with the isolated browser sandbox.
    Guarantees:
      1. Pre-flight SSRF & scheme validation before dispatch.
      2. Ephemeral session lifecycle: zero stored cookies or persistent state.
      3. Hard navigation limits: timeouts, max payload size, max redirects.
      4. Read-only text extraction and screenshots only.
    """

    def __init__(
        self,
        rpc_url: Optional[str] = None,
        limits: Optional[NavigationLimits] = None,
    ) -> None:
        self.rpc_url = (rpc_url or os.getenv(SANDBOX_BROWSER_URL_ENV, "")).rstrip("/")
        self.limits = limits or NavigationLimits()

    def browse(
        self,
        url: str,
        allowed_domains: Sequence[str] = (),
        denied_domains: Sequence[str] = (),
        take_screenshot: bool = False,
        timeout_ms: Optional[int] = None,
        max_bytes: Optional[int] = None,
    ) -> BrowseResponse:
        """
        Navigate to a webpage in the sandbox, extract text, and optionally capture screenshot.
        """
        # 1. Pre-flight security validation
        validate_sandbox_url(url, allowed_domains=allowed_domains, denied_domains=denied_domains)

        effective_timeout_ms = min(
            timeout_ms or self.limits.timeout_ms,
            30000,  # Hard ceiling 30s
        )
        effective_max_bytes = max_bytes or self.limits.max_content_bytes

        # A configured remote boundary is authoritative: denial and outage propagate.
        if self.rpc_url:
            return self._browse_rpc(
                url, allowed_domains, denied_domains, take_screenshot,
                effective_timeout_ms, effective_max_bytes,
            )
        from orchestrator_core.config import get_settings
        if get_settings().environment != "development" or os.getenv("SANDBOX_ALLOW_LOCAL", "").lower() != "true":
            raise SandboxSecurityError("Required browser sandbox is not configured")
        return self._browse_local(url, allowed_domains, denied_domains, take_screenshot,
                                  effective_timeout_ms, effective_max_bytes)

    def _browse_rpc(
        self,
        url: str,
        allowed_domains: Sequence[str],
        denied_domains: Sequence[str],
        take_screenshot: bool,
        timeout_ms: int,
        max_bytes: int,
    ) -> BrowseResponse:
        """Dispatch navigation request to sandbox container over HTTP RPC."""
        req_payload = BrowseRequest(
            url=url,
            allowed_domains=list(allowed_domains),
            denied_domains=list(denied_domains),
            timeout_ms=timeout_ms,
            take_screenshot=take_screenshot,
            max_bytes=max_bytes,
        )
        resp = requests.post(
            f"{self.rpc_url}/browse",
            json=req_payload.model_dump(),
            timeout=(timeout_ms / 1000.0) + 5.0,
            allow_redirects=False,
        )
        if resp.status_code == 403 or resp.status_code == 400:
            err_data = resp.json().get("detail", resp.text)
            raise SandboxSecurityError(f"Sandbox container security rejection: {err_data}")
        resp.raise_for_status()
        return BrowseResponse.model_validate(resp.json())

    def _browse_local(
        self,
        url: str,
        allowed_domains: Sequence[str],
        denied_domains: Sequence[str],
        take_screenshot: bool,
        timeout_ms: int,
        max_bytes: int,
    ) -> BrowseResponse:
        """Explicit development-only static reader; it never launches a local browser."""
        if take_screenshot:
            raise SandboxSecurityError("Screenshots require the isolated browser service")
        return self._browse_with_http_fallback(
            url, allowed_domains, timeout_ms, max_bytes, denied_domains,
        )

    def _browse_with_http_fallback(
        self,
        url: str,
        allowed_domains: Sequence[str],
        timeout_ms: int,
        max_bytes: int,
        denied_domains: Sequence[str] = (),
    ) -> BrowseResponse:
        """Explicit local static reader using the pinned transport."""
        from orchestrator_core.tools.read.shared_client import safe_get

        resp = safe_get(
            url,
            allowed_domains=tuple(allowed_domains),
            timeout_s=timeout_ms / 1000.0,
            max_bytes=max_bytes,
            max_redirects=self.limits.max_redirects,
            denied_domains=tuple(denied_domains),
        )
        html = resp.text
        # Clean HTML to text
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            for el in soup(["script", "style", "noscript", "nav", "header", "footer", "form", "svg"]):
                el.decompose()
            title = soup.title.string.strip() if soup.title and soup.title.string else ""
            body = soup.body or soup
            text = body.get_text(separator="\n", strip=True)
            text = re.sub(r"\n{3,}", "\n\n", text)
        except Exception:
            clean = re.sub(r"<(script|style|noscript|nav|header|footer|form|svg)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
            title_m = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
            title = title_m.group(1).strip() if title_m else ""
            clean = re.sub(r"<[^>]+>", " ", clean)
            text = re.sub(r"\s+", " ", clean).strip()

        is_truncated = False
        content_len = len(text.encode("utf-8"))
        if content_len > max_bytes:
            text = text[:max_bytes]
            is_truncated = True

        return BrowseResponse(
            url=resp.url or url,
            title=title,
            text_content=text,
            screenshot_b64=None,
            status_code=resp.status_code,
            content_length=content_len,
            is_truncated=is_truncated,
        )


# Global default client
default_sandbox_client = SandboxBrowserClient()
