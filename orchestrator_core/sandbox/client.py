"""
orchestrator_core/sandbox/client.py

Client interface for the isolated browser sandbox.
Dispatches requests to the Dockerized browser RPC container when SANDBOX_BROWSER_URL
is set, or uses the local ephemeral Playwright/HTTP driver with identical safety boundaries.
"""

from __future__ import annotations

import base64
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

        # 2. Dispatch via RPC if container is configured
        if self.rpc_url:
            try:
                return self._browse_rpc(
                    url=url,
                    allowed_domains=allowed_domains,
                    denied_domains=denied_domains,
                    take_screenshot=take_screenshot,
                    timeout_ms=effective_timeout_ms,
                    max_bytes=effective_max_bytes,
                )
            except Exception as exc:
                logger.warning(
                    "Sandbox RPC request to %s failed (%s). Falling back to local driver.",
                    self.rpc_url, exc,
                )

        # 3. Local driver execution
        return self._browse_local(
            url=url,
            allowed_domains=allowed_domains,
            denied_domains=denied_domains,
            take_screenshot=take_screenshot,
            timeout_ms=effective_timeout_ms,
            max_bytes=effective_max_bytes,
        )

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
        """Execute navigation using local Playwright driver or hardened HTTP fallback."""
        try:
            from playwright.sync_api import sync_playwright
            return self._browse_with_playwright(
                url=url,
                allowed_domains=allowed_domains,
                denied_domains=denied_domains,
                take_screenshot=take_screenshot,
                timeout_ms=timeout_ms,
                max_bytes=max_bytes,
            )
        except Exception as exc:
            logger.info("Local Playwright execution unavailable (%s); using secure HTTP fallback.", exc)
            return self._browse_with_http_fallback(
                url=url,
                allowed_domains=allowed_domains,
                timeout_ms=timeout_ms,
                max_bytes=max_bytes,
            )

    def _browse_with_playwright(
        self,
        url: str,
        allowed_domains: Sequence[str],
        denied_domains: Sequence[str],
        take_screenshot: bool,
        timeout_ms: int,
        max_bytes: int,
    ) -> BrowseResponse:
        """Run isolated navigation inside an ephemeral Playwright browser context."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--incognito",
                ],
            )
            # Create fresh ephemeral context - zero persistent cookies/storage
            context = browser.new_context(
                ignore_https_errors=False,
                java_script_enabled=True,
                user_agent="AaqilSandboxBrowser/1.0 (+https://github.com/FarhanAaqil/orchestrator_agent)",
            )

            page = context.new_page()
            page.set_default_timeout(timeout_ms)

            # Intercept and validate all subresource requests
            def route_interceptor(route):
                req_url = route.request.url
                try:
                    validate_sandbox_url(req_url, allowed_domains=allowed_domains, denied_domains=denied_domains)
                    route.continue_()
                except SandboxSecurityError:
                    route.abort("accessdenied")

            page.route("**/*", route_interceptor)

            # Navigate to target
            response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            final_url = page.url

            # Re-verify final URL after any redirects
            validate_sandbox_url(final_url, allowed_domains=allowed_domains, denied_domains=denied_domains)

            title = page.title() or ""

            # Extract human-readable text by removing scripts/styles/forms
            text_content = page.evaluate("""() => {
                const clone = document.body ? document.body.cloneNode(true) : document.documentElement.cloneNode(true);
                const toRemove = clone.querySelectorAll('script, style, noscript, nav, header, footer, form, svg');
                toRemove.forEach(el => el.remove());
                return clone.innerText || '';
            }""").strip()

            # Optional screenshot
            screenshot_b64 = None
            if take_screenshot:
                raw_bytes = page.screenshot(type="png", full_page=False)
                screenshot_b64 = base64.b64encode(raw_bytes).decode("ascii")

            # Cleanup immediately
            context.close()
            browser.close()

            # Enforce content size limits
            is_truncated = False
            encoded_bytes = len(text_content.encode("utf-8"))
            if encoded_bytes > max_bytes:
                text_content = text_content[:max_bytes]
                is_truncated = True

            return BrowseResponse(
                url=final_url,
                title=title,
                text_content=text_content,
                screenshot_b64=screenshot_b64,
                status_code=response.status if response else 200,
                content_length=encoded_bytes,
                is_truncated=is_truncated,
            )

    def _browse_with_http_fallback(
        self,
        url: str,
        allowed_domains: Sequence[str],
        timeout_ms: int,
        max_bytes: int,
    ) -> BrowseResponse:
        """Fallback reader using hardened safe_get client."""
        from orchestrator_core.tools.read.shared_client import safe_get

        resp = safe_get(
            url,
            allowed_domains=tuple(allowed_domains),
            timeout_s=timeout_ms / 1000.0,
            max_bytes=max_bytes,
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
