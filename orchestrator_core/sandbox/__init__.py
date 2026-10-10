"""
orchestrator_core/sandbox

Isolated browser sandbox package for safe web navigation.
"""

from orchestrator_core.sandbox.client import SandboxBrowserClient, default_sandbox_client
from orchestrator_core.sandbox.security import SandboxSecurityError, validate_sandbox_url
from orchestrator_core.sandbox.types import BrowseRequest, BrowseResponse, NavigationLimits

__all__ = [
    "SandboxBrowserClient",
    "default_sandbox_client",
    "SandboxSecurityError",
    "validate_sandbox_url",
    "BrowseRequest",
    "BrowseResponse",
    "NavigationLimits",
]
