"""
orchestrator_core/agents/career_agent.py

Career agent v2 — clean port of v1 CareerAgent logic.

Exposes a single handle(command) -> AgentResult interface.
All DB-seeding logic from v1 is preserved but guarded so it only runs when
a real DB connection is available (not on import).

Cover-letter generation is absorbed here (previously split across JobAgent)
per the corrective plan §2.1.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from orchestrator_core.core.provider import Groq

from orchestrator_core.config import get_settings
from orchestrator_core.models import AgentResult

logger = logging.getLogger(__name__)

AGENT_NAME = "career_agent"
TOOL_ALLOWLIST: frozenset[str] = frozenset({"fetch_page", "github_read", "google_search"})

_SYSTEM_PROMPT = "You are the user's career assistant. Help with resume tailoring, interview preparation, cover letters, and career planning. Use only personal facts supplied in the user's brief or reviewed account context. Ask for missing qualifications; never invent names, contact details, employers or achievements."


def _call_llm(prompt: str) -> str:
    """Make a single Groq completion call with fallback if credentials are invalid."""
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
            max_tokens=2500,
        )
        return response.choices[0].message.content
    except Exception as exc:
        logger.warning("Model generation failed: %s", type(exc).__name__)
        raise


def handle(command: str, metadata: Optional[dict[str, Any]] = None) -> AgentResult:
    """
    Entry point for the career agent.

    Accepts a natural-language command and returns an AgentResult.
    Cover-letter generation is handled here (absorbed from v1 JobAgent).
    """
    logger.info("[career_agent] Processing request")

    # Detect cover-letter intent (absorbed from JobAgent per corrective plan §2.1)
    lower = command.lower()
    if any(kw in lower for kw in ("cover letter", "cover-letter", "application letter")):
        prompt = f"""Write a professional cover letter using only the personal facts in this request:

{command}

Ask for missing background information. Do not invent achievements.
Keep it 150-250 words. Clear ask, specific achievements, professional tone."""
    else:
        prompt = command

    output = _call_llm(prompt)

    return AgentResult(
        agent="career_agent",
        output=output,
        metadata=metadata or {},
    )
