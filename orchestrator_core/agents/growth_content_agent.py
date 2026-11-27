"""
orchestrator_core/agents/growth_content_agent.py

Growth/Content agent v2.

Key difference from v1: this agent NEVER calls publishing SDKs directly.
Any publish action goes through request_approval() — the SDK import and
execution live exclusively in orchestrator_core/core/approval_gate.py.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from orchestrator_core.core.provider import Groq

from orchestrator_core.config import get_settings
from orchestrator_core.models import AgentResult

logger = logging.getLogger(__name__)

AGENT_NAME = "growth_content_agent"
TOOL_ALLOWLIST: frozenset[str] = frozenset({"google_search", "fetch_page", "propose_action"})

_SYSTEM_PROMPT = """You are the user's technical writing assistant.
Create clear, accurate content from the user's brief and supplied context.
Do not invent an author identity, employment, credentials, or personal achievements.
Use first person only for facts the user supplied about themselves.
Mark missing factual details for the user to complete before publishing."""


def _call_llm(prompt: str) -> str:
    settings = get_settings()
    try:
        client = Groq(api_key=settings.groq_api_key)
        response = client.chat.completions.create(
            model=settings.router_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.8,
            max_tokens=2500,
        )
        return response.choices[0].message.content
    except Exception as exc:
        logger.warning("Content generation failed: %s", type(exc).__name__)
        raise


def handle(command: str, metadata: Optional[dict[str, Any]] = None) -> AgentResult:
    """
    Entry point for the growth/content agent.

    Content generation always returns text. When the user asks to publish,
    the agent signals it via action_type so the caller can queue an approval.
    The agent NEVER imports or calls Hashnode/Dev.to SDKs directly.
    """
    logger.info("[growth_content_agent] Processing request")

    lower = command.lower()
    output = _call_llm(command)

    # Detect publish intent — signal for approval gate, never call SDK here
    action_type: Optional[str] = None
    if "publish" in lower and "hashnode" in lower:
        action_type = "publish_hashnode"
        logger.info("Publish intent detected — queuing for approval gate")
    elif "publish" in lower and ("devto" in lower or "dev.to" in lower):
        action_type = "publish_devto"
        logger.info("Publish intent detected — queuing for approval gate")

    meta = dict(metadata or {})
    if action_type:
        meta["approval_payload"] = {
            "title": output.splitlines()[0].lstrip("# ").strip() if output.strip() else "Untitled draft",
            "content": output,
        }
    if action_type == 'publish_hashnode':
        import re
        publication = re.search(r'\bpublication(?:_id| id)?\s*[:=]?\s+([a-fA-F0-9]{24})\b', command)
        if publication:
            meta['approval_payload']['publication_id'] = publication.group(1)
    return AgentResult(
        agent="growth_content_agent",
        output=output,
        action_type=action_type,
        metadata=meta,
    )
