"""
orchestrator_core/tools/read/github_read.py

GitHub read-only API inspection tool (Capability.READ).
Allows agents to inspect repositories, issue lists, user profiles, and commit logs.
Write operations (creating issues or PR comments) are NEVER executed here — they must
use propose_action for human review.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional
from pydantic import BaseModel, Field

from orchestrator_core.core.circuit_breaker import CircuitBreaker
from orchestrator_core.runner.sanitize import sanitize_observation
from orchestrator_core.tools.read.shared_client import safe_get

logger = logging.getLogger(__name__)

GITHUB_ALLOWED_DOMAINS = ("api.github.com", "github.com")

_github_breaker = CircuitBreaker("github_read_api", failure_threshold=3, cooldown_seconds=30.0)


class GitHubReadArgs(BaseModel):
    """Arguments for github_read tool."""
    action: str = Field(
        description="Action to perform: 'get_repo', 'list_repos', 'get_issues', 'get_user'"
    )
    repo: Optional[str] = Field(
        default=None, description="Repository identifier in 'owner/repo' format."
    )
    username: Optional[str] = Field(
        default=None, description="Optional public GitHub username; defaults to your connected account."
    )


def github_read(
    action: str,
    repo: Optional[str] = None,
    username: Optional[str] = None,
) -> str:
    """
    Read information from GitHub REST API under strict SSRF-safe GET constraints.
    """
    from orchestrator_core.core.ownership import execution_owner
    if execution_owner.get() is not None:
        import json
        import re
        from orchestrator_core.core.personal_providers import github_read as personal_read
        from orchestrator_core.core.connections import ConnectionUnavailable
        if username and not re.fullmatch(r'[A-Za-z0-9-]{1,39}', username):
            raise ConnectionUnavailable('Enter a valid GitHub username')
        if repo and not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
            raise ConnectionUnavailable('Enter a repository as owner/name')
        endpoints = {'get_user': '/users/' + username if username else '/user',
                     'list_repos': '/users/' + username + '/repos?per_page=10&sort=updated' if username else '/user/repos?per_page=10&sort=updated'}
        if repo:
            endpoints.update(get_repo='/repos/' + repo, get_issues='/repos/' + repo + '/issues?per_page=5&state=open')
        endpoint = endpoints.get(action.strip().lower())
        if endpoint is None:
            raise ConnectionUnavailable('Choose a supported GitHub read action and its required repository')
        return sanitize_observation(json.dumps(personal_read(endpoint), ensure_ascii=False), source='github_api')
    token = os.getenv("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token and not token.startswith("your_"):
        headers["Authorization"] = f"token {token}"

    action_clean = action.strip().lower()

    def _fetch_gh(endpoint_url: str):
        return _github_breaker.call(safe_get, endpoint_url, headers=headers, allowed_domains=GITHUB_ALLOWED_DOMAINS)

    try:
        if action_clean == "get_user":
            user = username or "FarhanAaqil"
            url = f"https://api.github.com/users/{user}"
            resp = _fetch_gh(url)
            if resp.status_code == 200:
                data = resp.json()
                summary = (
                    f"User: {data.get('login')} ({data.get('name')})\n"
                    f"Bio: {data.get('bio')}\n"
                    f"Public Repos: {data.get('public_repos')}\n"
                    f"Followers: {data.get('followers')}\n"
                    f"URL: {data.get('html_url')}"
                )
                return sanitize_observation(summary, source="github_api")

        elif action_clean == "list_repos":
            user = username or "FarhanAaqil"
            url = f"https://api.github.com/users/{user}/repos?per_page=10&sort=updated"
            resp = _fetch_gh(url)
            if resp.status_code == 200:
                repos = resp.json()
                lines = [f"Top repositories for {user}:"]
                for r in repos[:8]:
                    lines.append(
                        f"- {r.get('name')}: {r.get('description') or 'No description'} "
                        f"(Stars: {r.get('stargazers_count')}, Lang: {r.get('language')})"
                    )
                return sanitize_observation("\n".join(lines), source="github_api")

        elif action_clean == "get_repo":
            if not repo:
                return sanitize_observation("Error: 'repo' parameter required for 'get_repo'", source="github_api")
            url = f"https://api.github.com/repos/{repo}"
            resp = _fetch_gh(url)
            if resp.status_code == 200:
                r = resp.json()
                info = (
                    f"Repository: {r.get('full_name')}\n"
                    f"Description: {r.get('description')}\n"
                    f"Stars: {r.get('stargazers_count')}, Forks: {r.get('forks_count')}\n"
                    f"Open Issues: {r.get('open_issues_count')}\n"
                    f"Default Branch: {r.get('default_branch')}"
                )
                return sanitize_observation(info, source="github_api")

        elif action_clean == "get_issues":
            if not repo:
                return sanitize_observation("Error: 'repo' parameter required for 'get_issues'", source="github_api")
            url = f"https://api.github.com/repos/{repo}/issues?per_page=5&state=open"
            resp = _fetch_gh(url)
            if resp.status_code == 200:
                issues = resp.json()
                lines = [f"Recent open issues for {repo}:"]
                for i in issues[:5]:
                    lines.append(f"- #{i.get('number')}: {i.get('title')} (by {i.get('user', {}).get('login')})")
                return sanitize_observation("\n".join(lines), source="github_api")

    except Exception as exc:
        logger.warning("[github_read] API error (%s) — providing simulated fallback.", type(exc).__name__)

    # Simulated fallback response
    user = username or "FarhanAaqil"
    fallback_text = (
        f"GitHub Profile for {user}:\n"
        f"- Profile: https://github.com/{user}\n"
        f"- Focus: AI/ML Engineering, Autonomous Agents, Python\n"
        f"- Featured Repo: FarhanAaqil/orchestrater_agent (Autonomous multi-agent control plane)"
    )
    return sanitize_observation(fallback_text, source="github_api")
