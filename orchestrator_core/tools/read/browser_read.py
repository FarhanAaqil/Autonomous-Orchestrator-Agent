"""
orchestrator_core/tools/read/browser_read.py

Isolated browser reading tool (Capability.READ).
Navigates web pages via the Playwright browser sandbox with strict SSRF isolation,
ephemeral profile lifecycle, and wraps all extracted text in <untrusted_data> boundaries.
"""

from __future__ import annotations

import logging
from typing import Sequence
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from orchestrator_core.runner.sanitize import sanitize_observation
from orchestrator_core.sandbox.client import default_sandbox_client
from orchestrator_core.sandbox.security import SandboxSecurityError

logger = logging.getLogger(__name__)


class BrowserReadArgs(BaseModel):
    """Arguments for browser_read tool."""
    url: str = Field(description="The full HTTP/HTTPS URL of the web page to inspect.")
    allowed_domains: Sequence[str] = Field(
        default=(),
        description="Optional list of permitted domains to constrain navigation.",
    )
    take_screenshot: bool = Field(
        default=False,
        description="Whether to capture a visual screenshot of the rendered page.",
    )


def browser_read(
    url: str,
    allowed_domains: Sequence[str] = (),
    take_screenshot: bool = False,
    max_chars: int = 8000,
) -> str:
    """
    Browse a web page safely in the sandbox, extract text content, and wrap inside XML tags.
    """
    try:
        response = default_sandbox_client.browse(
            url=url,
            allowed_domains=allowed_domains,
            take_screenshot=take_screenshot,
        )
        hostname = urlparse(response.url).hostname or "browser_sandbox"

        formatted = (
            f"Title: {response.title}\n"
            f"URL: {response.url}\n\n"
            f"{response.text_content}"
        ).strip()

        if response.is_truncated:
            formatted += "\n\n[Notice: Page content was truncated to fit maximum payload ceiling]"

        if response.screenshot_b64:
            formatted += f"\n\n[Screenshot captured: {len(response.screenshot_b64)} chars base64 PNG]"

        return sanitize_observation(formatted, source=hostname, max_chars=max_chars)
    except SandboxSecurityError as sec_err:
        logger.warning("Sandbox security policy blocked browser navigation to %s: %s", url, sec_err)
        return sanitize_observation(f"Security Policy Violation: {sec_err}", source="browser_sandbox_security")
    except Exception as exc:
        logger.warning("browser_read failed for %s: %s", url, exc)
        return sanitize_observation(f"Error browsing page {url}: {exc}", source="browser_read")
