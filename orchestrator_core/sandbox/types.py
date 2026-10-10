"""
orchestrator_core/sandbox/types.py

Data structures and options for the isolated browser sandbox.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from pydantic import BaseModel, Field


@dataclass(frozen=True)
class NavigationLimits:
    """Hard operational safety bounds for browser navigation."""
    timeout_ms: int = 15000         # 15s default navigation timeout
    max_redirects: int = 5          # Max HTTP/JS redirect chain length
    max_content_bytes: int = 1048576  # 1 MB max content extraction threshold
    screenshot_enabled: bool = True


class BrowseRequest(BaseModel):
    """RPC request payload for sandbox browser navigation."""
    url: str = Field(description="Target HTTP/HTTPS URL to navigate to.")
    allowed_domains: list[str] = Field(default_factory=list, description="Optional domain allowlist.")
    denied_domains: list[str] = Field(default_factory=list, description="Optional domain denylist.")
    timeout_ms: int = Field(default=15000, ge=1000, le=30000, description="Page load timeout in milliseconds.")
    take_screenshot: bool = Field(default=False, description="Whether to capture a PNG screenshot.")
    extract_text_only: bool = Field(default=True, description="Whether to extract readable text.")
    max_bytes: int = Field(default=1048576, description="Maximum payload size in bytes.")


class BrowseResponse(BaseModel):
    """RPC response payload returned by sandbox browser."""
    url: str = Field(description="Final resolved URL after redirects.")
    title: str = Field(default="", description="Webpage title.")
    text_content: str = Field(default="", description="Extracted readable text content.")
    screenshot_b64: Optional[str] = Field(default=None, description="Base64-encoded PNG screenshot if requested.")
    status_code: int = Field(default=200, description="HTTP status code.")
    content_length: int = Field(default=0, description="Extracted content length in bytes.")
    is_truncated: bool = Field(default=False, description="True if content exceeded max_bytes.")
    error: Optional[str] = Field(default=None, description="Error message if navigation failed.")
