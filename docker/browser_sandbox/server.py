"""
docker/browser_sandbox/server.py

FastAPI RPC server running inside the Docker browser sandbox container.
Executes web navigation inside isolated, ephemeral Playwright browser contexts.
"""

from __future__ import annotations

import base64
import logging
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from security import SandboxSecurityError, validate_sandbox_url

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sandbox_server")

app = FastAPI(title="Playwright Browser Sandbox RPC", version="1.0.0")


class BrowseRequest(BaseModel):
    url: str
    allowed_domains: list[str] = Field(default_factory=list)
    denied_domains: list[str] = Field(default_factory=list)
    timeout_ms: int = Field(default=15000, ge=1000, le=30000)
    take_screenshot: bool = False
    max_bytes: int = 1048576


class BrowseResponse(BaseModel):
    url: str
    title: str = ""
    text_content: str = ""
    screenshot_b64: Optional[str] = None
    status_code: int = 200
    content_length: int = 0
    is_truncated: bool = False
    error: Optional[str] = None


@app.get("/health")
def health():
    return {"status": "ok", "sandbox": "playwright", "mode": "ephemeral"}


@app.post("/browse", response_model=BrowseResponse)
def browse(req: BrowseRequest):
    # Pre-flight security validation
    try:
        validate_sandbox_url(
            req.url,
            allowed_domains=req.allowed_domains,
            denied_domains=req.denied_domains,
        )
    except SandboxSecurityError as sec_err:
        raise HTTPException(status_code=403, detail=str(sec_err))

    try:
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
            # Ephemeral context - zero saved cookies or state
            context = browser.new_context(
                ignore_https_errors=False,
                java_script_enabled=True,
                user_agent="AaqilSandboxBrowser/1.0 (+https://github.com/FarhanAaqil/orchestrator_agent)",
            )
            page = context.new_page()
            page.set_default_timeout(req.timeout_ms)

            # Subresource SSRF validation
            def route_handler(route):
                try:
                    validate_sandbox_url(
                        route.request.url,
                        allowed_domains=req.allowed_domains,
                        denied_domains=req.denied_domains,
                    )
                    route.continue_()
                except SandboxSecurityError:
                    route.abort("accessdenied")

            page.route("**/*", route_handler)

            response = page.goto(req.url, wait_until="domcontentloaded", timeout=req.timeout_ms)
            final_url = page.url

            # Validate final redirect destination
            validate_sandbox_url(
                final_url,
                allowed_domains=req.allowed_domains,
                denied_domains=req.denied_domains,
            )

            title = page.title() or ""

            # Extract human-readable text stripped of scripts, styles, forms
            text_content = page.evaluate("""() => {
                const clone = document.body ? document.body.cloneNode(true) : document.documentElement.cloneNode(true);
                const toRemove = clone.querySelectorAll('script, style, noscript, nav, header, footer, form, svg');
                toRemove.forEach(el => el.remove());
                return clone.innerText || '';
            }""").strip()

            screenshot_b64 = None
            if req.take_screenshot:
                raw_bytes = page.screenshot(type="png", full_page=False)
                screenshot_b64 = base64.b64encode(raw_bytes).decode("ascii")

            context.close()
            browser.close()

            encoded_bytes = len(text_content.encode("utf-8"))
            is_truncated = False
            if encoded_bytes > req.max_bytes:
                text_content = text_content[:req.max_bytes]
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
    except SandboxSecurityError as sec_err:
        raise HTTPException(status_code=403, detail=str(sec_err))
    except Exception as exc:
        logger.exception("Error executing browse request for %s: %s", req.url, exc)
        raise HTTPException(status_code=500, detail=str(exc))
