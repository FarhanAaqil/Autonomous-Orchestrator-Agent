"""Canonical contracts shared by proposal producers, reviewers and executors."""
from dataclasses import dataclass
from typing import Literal
import re

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from orchestrator_core.exceptions import SecurityPolicyViolationError


class ActionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    run_id: str | None = None


class EmailPayload(ActionPayload):
    to_email: str
    subject: str = Field(min_length=1, max_length=998)
    body: str = Field(min_length=1, max_length=100_000)

    @field_validator("to_email")
    @classmethod
    def single_address(cls, value):
        if not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", value):
            raise ValueError("One plain email address is required")
        return value

    @field_validator("subject")
    @classmethod
    def no_header_injection(cls, value):
        if "\r" in value or "\n" in value:
            raise ValueError("Subject cannot contain line breaks")
        return value


class PublicationPayload(ActionPayload):
    title: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=100_000)


class IssuePayload(ActionPayload):
    repo: str = Field(pattern=r"^[\w.-]+/[\w.-]+$")
    title: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=100_000)


class CommentPayload(ActionPayload):
    repo: str = Field(pattern=r"^[\w.-]+/[\w.-]+$")
    issue_number: int = Field(gt=0)
    body: str = Field(min_length=1, max_length=100_000)


class SocialPayload(ActionPayload):
    content: str = Field(min_length=1, max_length=3000)


@dataclass(frozen=True)
class ActionSpec:
    schema: type[ActionPayload]
    target_field: str | None
    agents: frozenset[str]
    adapter: Literal["smtp", "unavailable"] = "unavailable"


ACTION_CATALOG = {
    "send_email": ActionSpec(EmailPayload, "to_email", frozenset({"email_agent", "orchestrator"}), "smtp"),
    "publish_hashnode": ActionSpec(PublicationPayload, None, frozenset({"growth_content_agent", "orchestrator"})),
    "publish_devto": ActionSpec(PublicationPayload, None, frozenset({"growth_content_agent", "orchestrator"})),
    "github_create_issue": ActionSpec(IssuePayload, "repo", frozenset({"github_agent", "orchestrator"})),
    "github_comment": ActionSpec(CommentPayload, "repo", frozenset({"github_agent", "orchestrator"})),
    "linkedin_post": ActionSpec(SocialPayload, None, frozenset({"linkedin_agent", "orchestrator"})),
}
ACTION_ALIASES = {"github_issue": "github_create_issue", "github_issue_create": "github_create_issue", "linkedin_post_text": "linkedin_post"}


def normalize_action(action_type, payload, target=None):
    name = ACTION_ALIASES.get(action_type.strip().lower(), action_type.strip().lower())
    spec = ACTION_CATALOG.get(name)
    if not spec:
        raise SecurityPolicyViolationError(f"Unsupported action: {name}")
    data = dict(payload)
    declared_target = data.pop("target", None)
    aliases = ("to_email", "to", "recipient") if name == "send_email" else ("repo", "repository") if spec.target_field == "repo" else ()
    values = [str(data[k]).strip() for k in aliases if k in data and data[k] is not None]
    if values:
        if len(set(values)) != 1:
            raise SecurityPolicyViolationError("Conflicting recipient aliases")
        for key in aliases:
            data.pop(key, None)
        data[spec.target_field] = values[0]
    try:
        canonical = spec.schema.model_validate(data).model_dump(exclude_none=True)
    except ValidationError as exc:
        raise SecurityPolicyViolationError(f"Invalid {name} payload: {exc.error_count()} field error(s)") from exc
    canonical_target = canonical[spec.target_field] if spec.target_field else name
    if any(str(t).strip() != canonical_target for t in (target, declared_target) if t is not None):
        raise SecurityPolicyViolationError("Target does not match the canonical action recipient")
    return name, canonical, canonical_target


def require_adapter(action_type):
    spec = ACTION_CATALOG.get(action_type)
    if spec is None or spec.adapter == "unavailable":
        raise SecurityPolicyViolationError(f"No execution adapter is available for {action_type}")


def action_schemas():
    from orchestrator_core.config import get_settings
    mode = get_settings().action_execution_mode
    return {name: {"payload": spec.schema.model_json_schema(), "adapter": spec.adapter,
                   "execution_mode": mode if spec.adapter != "unavailable" else "unavailable",
                   "agents": sorted(spec.agents)} for name, spec in ACTION_CATALOG.items()}
