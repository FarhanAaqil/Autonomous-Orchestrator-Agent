"""Fulfil browser reads through the gateway; never allow native browser egress."""
import base64
import logging
import time
import requests

logger = logging.getLogger("sandbox_boundary")
EGRESS_URL = "http://172.30.90.2:8889/read"


class ReadBoundary:
    def __init__(self, req):
        self.req = req
        self.deadline = time.monotonic() + req.timeout_ms / 1000
        self.remaining = req.max_bytes
        self.count = 0
        self.error = None
        self.final_url = req.url

    def handle(self, route):
        try:
            self.count += 1
            if route.request.method not in ("GET", "HEAD"):
                raise ValueError("Mutating browser method blocked")
            if self.count > 64 or self.remaining <= 0:
                raise ValueError("Page resource budget exhausted")
            remaining_time = self.deadline - time.monotonic()
            if remaining_time <= 0:
                raise ValueError("Page deadline exceeded")
            response = requests.post(
                EGRESS_URL, timeout=remaining_time,
                json={"url": route.request.url, "method": route.request.method,
                      "allowed_domains": self.req.allowed_domains,
                      "denied_domains": self.req.denied_domains,
                      "max_bytes": self.remaining, "timeout_s": min(remaining_time, 30)},
                allow_redirects=False,
            )
            response.raise_for_status()
            data = response.json()
            content = base64.b64decode(data["body"], validate=True)
            self.remaining -= len(content)
            if self.remaining < 0:
                raise ValueError("Page resource budget exhausted")
            if route.request.is_navigation_request():
                self.final_url = data["url"]
            route.fulfill(status=data["status"], body=content, headers={
                "Content-Type": data["content_type"],
                "Content-Security-Policy": "script-src 'none'; form-action 'none'; worker-src 'none'; connect-src 'none'",
            })
        except Exception as exc:
            self.error = str(exc)
            logger.warning("Browser request blocked: %s", self.error)
            route.abort("accessdenied")
