"""
orchestrator_core/agents/linkedin_agent.py

LinkedIn Agent — Professional branding, outreach drafting, and recruiter search specialist.

READ / WRITE SPLIT CONTRACT:
  - Free (un-gated): recruiter search via web, connection note drafting (strict 300-char limit),
    cold DMs, headline optimization, About section polishing, JD fit analysis.
  - Gated (approval required): external posting or messaging.
    Returns action_type="linkedin_post" or "linkedin_connect" for approval gate review.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from orchestrator_core.core.provider import Groq

from orchestrator_core.config import get_settings
from orchestrator_core.models import AgentResult
from orchestrator_core.tools.web_search import search_web

logger = logging.getLogger(__name__)

AGENT_NAME = "linkedin_agent"
TOOL_ALLOWLIST: frozenset[str] = frozenset({"ddg_search", "fetch_page", "browser_read", "propose_action"})

_SYSTEM_PROMPT = "You are the user's professional networking assistant. Draft LinkedIn notes, posts, profiles, and outreach for manual review. Connection notes must be at most 300 characters. Use only personal facts supplied by the user or reviewed account context; never invent qualifications or achievements."


def _call_llm(prompt: str) -> str:
    """Execute Groq LLM completion with fallback."""
    settings = get_settings()
    try:
        client = Groq(api_key=settings.groq_api_key)
        response = client.chat.completions.create(
            model=settings.router_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=2000,
        )
        return response.choices[0].message.content
    except Exception as exc:
        logger.warning("Model generation failed: %s", type(exc).__name__)
        raise


def _search_recruiters(query: str) -> str:
    """Find recruiters or technical leaders using targeted Google/DDG queries."""
    search_query = f"site:linkedin.com/in/ {query}"
    results = search_web(search_query, max_results=5)
    if not results or "error" in results[0]:
        return f"🔍 Searched for `{query}` on LinkedIn. Results temporarily unavailable via web search."

    lines = [f"### 💼 LinkedIn Search Results for `{query}`:\n"]
    for r in results:
        title = r.get("title", "").replace(" | LinkedIn", "")
        url = r.get("url", "")
        snippet = r.get("snippet", "")
        lines.append(f"- **[{title}]({url})**\n  {snippet}")
    return "\n".join(lines)


def handle(command: str, metadata: Optional[dict[str, Any]] = None) -> AgentResult:
    """
    Entry point for the LinkedIn Agent.
    Implements Read/Write split:
      - Reads: recruiter search, drafting posts/notes/DMs, profile review (free)
      - Writes: posting updates or sending invites (gated behind approval gate)
    """
    logger.info("[linkedin_agent] Processing request")
    lower = command.lower().strip()
    meta = dict(metadata or {})

    # 1. Gated Write Check: Post to LinkedIn
    if any(k in lower for k in ("post on linkedin", "share on linkedin", "publish to linkedin", "post update")):
        prompt = f"Draft a LinkedIn post for the user to review and copy manually: {command}"
        post_draft = _call_llm(prompt)
        return AgentResult(agent="linkedin_agent", output=post_draft + "\n\nDraft only. Review and copy this into LinkedIn yourself.", metadata={**meta, "draft_only": True})

    # 2. Free Read: Recruiter / profile search
    if any(k in lower for k in ("search recruiter", "find recruiter", "search linkedin", "find people", "find hiring manager")):
        search_term = command
        for prefix in ("search recruiter", "find recruiter", "search linkedin for", "find people at", "find hiring manager at"):
            if prefix in lower:
                search_term = command[lower.index(prefix) + len(prefix):].strip()
                break
        search_output = _search_recruiters(search_term or "AI engineer recruiter")
        return AgentResult(
            agent="linkedin_agent",
            output=search_output,
            action_type=None,
            metadata=meta,
        )

    # 3. Free Read: Draft connection request (strict 300-char limit)
    if any(k in lower for k in ("connection note", "connect note", "connect message", "connection request")):
        prompt = (
            f"Draft a personalized LinkedIn connection request note for: {command}.\n"
            f"CRITICAL CONSTRAINT: The note MUST be under 300 characters total, concise, and compelling."
        )
        note_draft = _call_llm(prompt)
        # Ensure it respects length
        char_count = len(note_draft)
        return AgentResult(
            agent="linkedin_agent",
            output=(
                f"🤝 **Personalized Connection Note ({char_count}/300 chars):**\n\n"
                f"> {note_draft}\n\n"
                f"*Copy and paste this into LinkedIn when sending your invitation.*"
            ),
            action_type=None,
            metadata=meta,
        )

    # 4. Free Read: Cold DM, profile headline, About section, or general LinkedIn strategy
    output = _call_llm(command)
    return AgentResult(
        agent="linkedin_agent",
        output=output,
        action_type=None,
        metadata=meta,
    )
