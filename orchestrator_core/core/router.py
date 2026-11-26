"""
orchestrator_core/core/router.py

LLM-based command router.

classify(command) -> RouterResult | ClarificationNeeded

All Groq calls go through the module-level CircuitBreaker so that repeated
LLM failures fail-fast instead of stacking timeout threads.
Confidence threshold is read lazily from settings — no global state on import.
"""

from __future__ import annotations

import json
import logging
import re
import hashlib
import time
from typing import Union

from orchestrator_core.core.provider import Groq

from orchestrator_core.config import get_settings
from orchestrator_core.core.circuit_breaker import CircuitBreaker
from orchestrator_core.models import RouterResult, ClarificationNeeded

logger = logging.getLogger(__name__)

# Module-level breaker — shared across all classify() calls in the process.
# 3 consecutive Groq failures → OPEN for 30 s.
_groq_breaker = CircuitBreaker(service="groq_router", failure_threshold=3, cooldown_seconds=30.0)

# In-memory LRU/TTL cache for repeated router classifications
_classification_cache: dict[str, tuple[float, Union[RouterResult, ClarificationNeeded]]] = {}
ROUTER_CACHE_TTL = 300.0  # 5 minutes
ROUTER_CACHE_MAX_ENTRIES = 512


def clear_router_cache() -> None:
    """Clear the in-memory router classification cache."""
    _classification_cache.clear()

SUPPORTED_AGENTS = {
    "career_agent": "Resume tailoring, skill gaps, interview prep, career roadmaps, cover letters.",
    "research_agent": "Academic paper writing, journal search, research summaries, ArXiv paper analysis.",
    "growth_content_agent": "Technical blog posts, Dev.to/Hashnode publishing, devlogs, technical writing, Twitter threads.",
    "critic_agent": "Quality critique and improvement of cover letters, posts, papers, emails, and code.",
    "info_agent": "System architecture, how agents/pipelines/approvals work, Farhan Aaqil's projects portfolio, and documentation.",
    "email_agent": "Checking email inbox, reading unread messages, drafting recruiter outreach, and sending emails.",
    "github_agent": "GitHub repositories, user profiles, commit history, README generation, commit messages, creating issues or PR comments.",
    "linkedin_agent": "LinkedIn networking, recruiter discovery, 300-character connection notes, cold DMs, headline/profile optimization, and LinkedIn posts.",
    "general_chat_agent": "Casual conversation, general brainstorming, high-level technical advice, chitchat, greetings, and Toji companion.",
}

_ROUTER_SYSTEM_PROMPT = """\
You are a precise router for a multi-agent AI assistant system.
Your job is to classify user commands to exactly one agent and return a confidence score.

Available agents:
{agent_list}

Return a JSON object with this exact shape:
{{
  "agent": "<agent_name>",
  "confidence": <0.0-1.0>,
  "reasoning": "<one sentence>"
}}

Rules:
- agent must be one of the agent names above — no other values.
- confidence must be a float between 0.0 and 1.0.
- If the command is ambiguous between two agents, set confidence below 0.6.
- reasoning must be a concise explanation (under 20 words).
- Never add extra keys. Return ONLY the JSON object.
""".strip()


def _build_system_prompt() -> str:
    agent_list = "\n".join(f"- {k}: {v}" for k, v in SUPPORTED_AGENTS.items())
    return _ROUTER_SYSTEM_PROMPT.format(agent_list=agent_list)


def _heuristic_classify(command: str) -> dict:
    """Route explicit intent before topic mentions; never execute instructions here."""
    import difflib
    lower = command.lower().strip()
    # Correct close misspellings of routing vocabulary, not arbitrary user text.
    vocabulary = ('skill', 'skills', 'analysis', 'resume', 'email', 'emails', 'inbox',
                  'unread', 'summarize', 'review', 'research', 'abstract', 'linkedin',
                  'github', 'career', 'interview', 'journal', 'critique')
    words = re.findall(r"[a-z]+|[^a-z]+", lower)
    for index, word in enumerate(words):
        if word.isalpha() and len(word) >= 4 and word not in vocabulary:
            matches = difflib.get_close_matches(word, vocabulary, n=1, cutoff=0.82)
            if matches:
                words[index] = matches[0]
    text = ''.join(words)

    def has(pattern):
        return re.search(pattern, text) is not None

    def result(agent, confidence=0.95):
        return {'agent': agent, 'confidence': confidence,
                'reasoning': 'Offline intent rules selected ' + agent + '.'}

    # Treat attempts to override policy as conversation, never a write intent.
    if has(r'\b(ignore|bypass|disable|override)\b.{0,45}\b(instructions|safety|rules|approval|policy|security)\b|\bdeveloper mode\b'):
        return result('general_chat_agent')
    # Evaluation is a task of its own even when its object mentions another agent.
    if has(r'\b(critique|score|grade|rate|evaluate)\b|\breview\b(?!ed)|\bcheck\b.{0,30}\b(quality|logical errors|tone|clarity)\b'):
        if not has(r'\b(peer review|peer reviewed|reviewers|pull request|code review)\b'):
            return result('critic_agent')
    # A compound job search followed by correspondence is a career workflow.
    if has(r'\b(find|search|track|apply)\b.{0,25}\b(jobs?|internships?|opportunit(?:y|ies)|applications?)\b'):
        return result('career_agent')
    if has(r'\b(emails?|inbox|gmail|mail|thank[ -]you note)\b'):
        return result('email_agent')
    # Content creation outranks the destination or subject of the content.
    if has(r'\b(blog|dev\.to|devto|hashnode|tweet|twitter|devlog|newsletter|captions?|social media|content ideas|seo)\b|\b(write|draft|create|generate)\b.{0,25}\b(announcement|post|thread|content)\b'):
        return result('growth_content_agent')
    if has(r'\b(github|repos?|repository|repositories|commits?|prs?|pull requests?|release notes|issues?)\b'):
        return result('github_agent')
    if has(r'\b(linkedin|recruiters?|inmail|networking|connection note|connect note|cold dm|influencers?)\b|\b(find|search|connect)\b.{0,25}\b(people|profiles|someone)\b'):
        return result('linkedin_agent')
    if has(r'\b(resume|cv|jobs?|cover[ -]letter|interview|career|skills?|internship|applications?|elevator pitch|offers?|salary|salaries)\b'):
        return result('career_agent')
    if has(r'\b(papers?|arxiv|academic|research|journals?|literature|predatory|cite|citation|reviewers|neurips|state of the art|continual learning)\b|\bcompare\b.{0,35}\b(transformer|lstm|architectures)\b'):
        return result('research_agent')
    if has(r'\b(orchestrator|circuit breaker|router|approval gate|scheduler|sse|compare-and-set|quarantined|prompt injection|system documentation|farhan)\b'):
        return result('info_agent')
    if has(r'^\s*(what should i do|what next|which one)\s*[?.!]*$'):
        return result('career_agent', 0.45)
    return result('general_chat_agent', 0.75)


def _call_groq(command: str, allow_fallback: bool = True) -> dict:
    """Make the raw Groq API call. Wrapped by circuit breaker externally."""
    settings = get_settings()
    try:
        client = Groq(api_key=settings.groq_api_key)
        response = client.chat.completions.create(
            model=settings.router_model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _build_system_prompt()},
                {"role": "user", "content": command},
            ],
            temperature=0.0,
            max_tokens=200,
        )
        raw = response.choices[0].message.content
        # Strip any markdown fences the model might add despite JSON mode
        if "```" in raw:
            match = re.search(r"```(?:json)?(.*?)```", raw, re.DOTALL)
            if match:
                raw = match.group(1).strip()
        return json.loads(raw)
    except Exception as exc:
        err_msg = str(exc).lower()
        if allow_fallback and (
            "api_key" in err_msg
            or "401" in err_msg
            or "unauthorized" in err_msg
            or "invalid api key" in err_msg
            or "json_validate_failed" in err_msg
            or "failed to validate json" in err_msg
            or "400" in err_msg
        ):
            logger.warning("[router] Groq API returned error (%s) — using heuristic routing.", type(exc).__name__)
            return _heuristic_classify(command)
        raise


def get_circuit_status() -> dict:
    """Return circuit breaker diagnostic metrics."""
    return {
        "service": _groq_breaker.service,
        "state": _groq_breaker.state,
        "consecutive_failures": _groq_breaker._consecutive_failures,
        "failure_threshold": _groq_breaker.failure_threshold,
    }


def reset_circuit_breaker() -> None:
    """Manually reset router circuit breaker to CLOSED."""
    _groq_breaker.reset()



def prompt_hash(command: str) -> str:
    """Return a short hash of the system prompt + command for staleness tracking."""
    payload = _build_system_prompt() + command
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def classify(command: str, use_cache: bool = True, allow_fallback: bool = True) -> Union[RouterResult, ClarificationNeeded]:
    """
    Classify a user command and return either a RouterResult or a ClarificationNeeded.

    Goes through the circuit breaker — raises CircuitOpenError if the breaker
    is OPEN (i.e., Groq has been failing repeatedly).
    Uses server-side in-memory caching to eliminate redundant LLM calls.
    """
    from orchestrator_core.core.ownership import execution_owner
    cache_key = str(execution_owner.get()) + ":" + command.strip().lower()
    if use_cache and allow_fallback and cache_key in _classification_cache:
        cached_time, cached_result = _classification_cache[cache_key]
        if time.monotonic() - cached_time < ROUTER_CACHE_TTL:
            logger.debug("[router] Classification cache hit")
            return cached_result

    settings = get_settings()
    threshold = settings.router_confidence_threshold

    data = _groq_breaker.call(_call_groq, command) if allow_fallback else _groq_breaker.call(lambda value: _call_groq(value, allow_fallback=False), command)

    agent = data.get("agent", "").strip()
    confidence = float(data.get("confidence", 0.0))
    reasoning = data.get("reasoning", "")

    if agent not in SUPPORTED_AGENTS or confidence < threshold:
        # Determine candidate list: always include the returned agent if valid
        candidates = list(SUPPORTED_AGENTS.keys()) if agent not in SUPPORTED_AGENTS else [agent]
        # Add the second-most-likely agent if model returned a valid one
        if agent in SUPPORTED_AGENTS and len(candidates) == 1:
            # Expand candidates to the full list minus the returned one so caller
            # can surface them as alternatives
            candidates = [agent] + [a for a in SUPPORTED_AGENTS if a != agent]

        result = ClarificationNeeded(
            candidates=candidates[:3],
            reasoning=reasoning or f"Confidence {confidence:.0%} is below the {threshold:.0%} threshold.",
        )
    else:
        result = RouterResult(agent=agent, confidence=confidence, reasoning=reasoning)

    if use_cache and allow_fallback:
        if len(_classification_cache) >= ROUTER_CACHE_MAX_ENTRIES:
            oldest_keys = sorted(_classification_cache, key=lambda k: _classification_cache[k][0])[:100]
            for k in oldest_keys:
                _classification_cache.pop(k, None)
        _classification_cache[cache_key] = (time.monotonic(), result)

    return result
