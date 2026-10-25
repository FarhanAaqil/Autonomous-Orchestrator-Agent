"""
orchestrator_core/core/approval_gate.py

The single most critical module in the service.

APPROVAL SAFETY CONTRACT:
  - Agents call request_approval(action_type, payload) to queue an action for review.
  - A human (or authorized caller) calls approve/reject via the HTTP routes.
  - execute_approved(approval_id) executes the stored payload — it takes NO payload
    argument. This means a compromised or buggy caller cannot substitute a different
    payload than what was approved. The executor always loads from the immutable DB row.
  - The state machine is enforced by compare-and-set SQL transactions:
      pending → approved → executing → executed
      pending → rejected
      pending | approved → expired (checked by execute_approved)
  - Two concurrent execute_approved() calls on the same id will race on the
    UPDATE ... WHERE status = 'approved' — exactly one wins, the other raises
    ApprovalClaimConflictError.
  - _dispatch_action is the ONLY function in this codebase allowed to import
    email/publishing SDKs. Enforced by CI grep/AST (see Day 7).

# SDK_EXECUTOR: this module is the sole executor of email/publish SDKs.
# Do NOT import smtplib, hashnode, devto, or similar SDKs anywhere else.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from orchestrator_core.config import get_settings
from orchestrator_core.core.action_catalog import normalize_action, require_adapter
from orchestrator_core.core.policy import execution_origin, require_execution
from orchestrator_core.exceptions import (
    ApprovalAlreadyExecutedError,
    ApprovalClaimConflictError,
    ApprovalExpiredError,
    ApprovalHashMismatchError,
    ApprovalNotFoundError,
    ApprovalNotGrantedError,
    ApprovalSignatureInvalidError,
    ApprovalSupersededError,
    ApprovalTamperedError,
    IdempotencyConflictError,
    SecurityPolicyViolationError,
)
from orchestrator_core.storage.db import log_audit

logger = logging.getLogger(__name__)

# Default expiry window for pending approvals
_DEFAULT_EXPIRY_HOURS = 24

# Denylisted targets for SEC-08 policy enforcement
DENYLISTED_TARGETS = {
    "blocked@example.com",
    "malicious.com",
    "attacker@evil.com",
    "spam@spam.com",
}


# ── Canonicalization & Hash Helpers (SEC-02) ──────────────────────────────────

def compute_payload_hash(
    action_type: str,
    payload: dict[str, Any] | str,
    target: Optional[str] = None,
) -> str:
    """
    Compute deterministic SHA-256 hash across action_type, target, and canonical payload JSON.
    SEC-02: Any change to payload, target, or action_type alters this hash.
    """
    if isinstance(payload, str):
        payload_dict = json.loads(payload)
    else:
        payload_dict = payload
    canonical_json = json.dumps(payload_dict, separators=(",", ":"), sort_keys=True)
    target_str = target or ""
    canonical_input = f"{action_type}:{target_str}:{canonical_json}"
    return hashlib.sha256(canonical_input.encode("utf-8")).hexdigest()


def extract_target(action_type: str, payload: dict[str, Any]) -> Optional[str]:
    """Auto-extract recipient/channel/repository target from payload."""
    if "target" in payload and payload["target"]:
        return str(payload["target"])
    if action_type == "send_email":
        return payload.get("to_email") or payload.get("to") or payload.get("recipient")
    if action_type in ("github_create_issue", "github_comment"):
        return payload.get("repo") or payload.get("repository")
    if action_type in ("publish_hashnode", "publish_devto", "linkedin_post"):
        return payload.get("platform") or action_type
    return None


# ── HMAC Signing & Verification (SEC-03) ──────────────────────────────────────

def generate_approval_signature(
    approval_id: str,
    approved_hash: str,
    decided_at: str,
    secret: Optional[str] = None,
) -> str:
    """
    HMAC-SHA256 signature over (approval_id, approved_hash, decided_at).
    SEC-03: Signed with EXECUTOR_HMAC_SECRET. DB tampering by agents/tools cannot forge this.
    """
    if secret is None:
        secret = get_settings().executor_hmac_secret
    message = f"{approval_id}:{approved_hash}:{decided_at}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def verify_approval_signature(
    approval_id: str,
    approved_hash: str,
    decided_at: str,
    signature: Optional[str],
    secret: Optional[str] = None,
) -> bool:
    """Verify HMAC signature against expected secret."""
    if not signature:
        return False
    expected = generate_approval_signature(approval_id, approved_hash, decided_at, secret)
    return hmac.compare_digest(expected, signature)


# ── Recipient Policy Evaluation (SEC-08) ──────────────────────────────────────

def evaluate_target_policy(
    action_type: str,
    target: Optional[str],
    db: sqlite3.Connection,
) -> dict[str, Any]:
    """
    SEC-08: Evaluate recipient/target policy.
    - Check against target denylist.
    - Tag 'first-time recipient' as high risk if target hasn't been executed before.
    """
    if not target:
        return {"risk": "low", "first_time": False, "allowed": True}

    target_lower = target.strip().lower()
    for denied in DENYLISTED_TARGETS:
        if denied in target_lower:
            return {
                "risk": "critical",
                "first_time": True,
                "allowed": False,
                "reason": f"Target '{target}' is on the security denylist (SEC-08).",
            }

    # Check prior successful executions
    prior = db.execute(
        "SELECT 1 FROM approvals WHERE target = ? AND status = 'executed' LIMIT 1",
        (target,),
    ).fetchone()

    is_first_time = prior is None
    risk = "high" if is_first_time else "low"
    return {
        "risk": risk,
        "first_time": is_first_time,
        "allowed": True,
        "reason": "First-time recipient requires heightened scrutiny." if is_first_time else "Target verified by prior executions.",
    }


# ── Request ────────────────────────────────────────────────────────────────────

def request_approval(
    action_type: str,
    payload: dict[str, Any],
    db: sqlite3.Connection,
    expiry_hours: int = _DEFAULT_EXPIRY_HOURS,
    target: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    source_agent: Optional[str] = None,
    session_id: Optional[str] = None,
) -> str:
    """
    Queue an action for human review.

    Inserts a 'pending' row into the approvals table and returns the approval_id.
    Stores canonical payload and bound payload_hash.
    """
    action_type, payload, target = normalize_action(action_type, payload, target)
    origin_agent, origin_session = execution_origin.get()
    source_agent = source_agent or origin_agent
    session_id = session_id or origin_session
    require_execution(db, source_agent, action_type)

    # SEC-04 Idempotent request resolution
    if idempotency_key is not None:
        existing = db.execute(
            "SELECT id, status FROM approvals WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if existing:
            if existing["status"] == "executed":
                raise IdempotencyConflictError(idempotency_key)
            return existing["id"]

    # SEC-08 Policy check
    policy = evaluate_target_policy(action_type, target, db)
    if not policy["allowed"]:
        raise SecurityPolicyViolationError(policy["reason"])

    approval_id = str(uuid.uuid4())
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    payload_hash = compute_payload_hash(action_type, payload, target)
    idempotency_key = idempotency_key or f"idem_{approval_id}"
    created_at = datetime.now(timezone.utc)
    expires_at = created_at + timedelta(hours=expiry_hours)

    with db:
        db.execute(
            """
            INSERT INTO approvals (
                id, action_type, payload_json, target, payload_hash,
                status, idempotency_key, created_at, expires_at, source_agent, session_id
            )
            VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)
            """,
            (
                approval_id,
                action_type,
                payload_json,
                target,
                payload_hash,
                idempotency_key,
                created_at.isoformat(),
                expires_at.isoformat(),
                source_agent,
                session_id,
            ),
        )

    log_audit(
        db,
        actor="agent",
        event="approval_requested",
        entity="approval",
        entity_id=approval_id,
        detail={
            "action_type": action_type,
            "target": target,
            "payload_hash": payload_hash,
            "idempotency_key": idempotency_key,
            "risk": policy["risk"],
        },
    )

    logger.info(
        "Approval queued — id=%s action_type=%s target=%s expires_at=%s hash=%s",
        approval_id, action_type, target, expires_at.isoformat(), payload_hash,
    )
    return approval_id


# ── State transitions ──────────────────────────────────────────────────────────

def approve(
    approval_id: str,
    db: sqlite3.Connection,
    expected_hash: Optional[str] = None,
) -> None:
    """
    Transition a pending approval to 'approved' state.
    SEC-02: Verifies current DB payload hash matches stored hash.
    TOCTOU: If expected_hash is provided, verifies displayed hash matches DB hash.
    SEC-03: Computes and persists HMAC signature with server secret.
    """
    row = db.execute(
        "SELECT id, action_type, payload_json, target, payload_hash, status FROM approvals WHERE id = ?",
        (approval_id,),
    ).fetchone()

    if row is None:
        raise ApprovalNotFoundError(approval_id)
    if row["status"] == "superseded":
        raise ApprovalSupersededError(approval_id)
    if row["status"] != "pending":
        raise ApprovalNotGrantedError(approval_id, row["status"])

    # TOCTOU check against displayed expected_hash
    stored_hash = row["payload_hash"]
    if expected_hash is not None and expected_hash != stored_hash:
        raise ApprovalHashMismatchError(approval_id, expected_hash, stored_hash)

    # SEC-02 Integrity check: recalculate hash from raw DB content
    recomputed_hash = compute_payload_hash(row["action_type"], row["payload_json"], row["target"])
    if recomputed_hash != stored_hash:
        log_audit(
            db,
            actor="owner",
            event="tampering_detected_at_approve",
            entity="approval",
            entity_id=approval_id,
            detail={"recomputed": recomputed_hash, "stored": stored_hash},
        )
        raise ApprovalTamperedError(approval_id)

    # SEC-03: Sign approval with HMAC
    require_adapter(row["action_type"])
    decided_at = datetime.now(timezone.utc).isoformat()
    approved_hash = stored_hash
    signature = generate_approval_signature(approval_id, approved_hash, decided_at)

    with db:
        db.execute(
            """
            UPDATE approvals
            SET status = 'approved',
                decided_at = ?,
                approved_hash = ?,
                approval_signature = ?
            WHERE id = ? AND status = 'pending'
            """,
            (decided_at, approved_hash, signature, approval_id),
        )

    log_audit(
        db,
        actor="owner",
        event="approval_granted",
        entity="approval",
        entity_id=approval_id,
        detail={"approved_hash": approved_hash, "decided_at": decided_at},
    )
    logger.info("Approval approved — id=%s hash=%s", approval_id, approved_hash)


def reject(approval_id: str, db: sqlite3.Connection, reason: Optional[str] = None) -> None:
    """Transition a pending approval to 'rejected' state."""
    row = db.execute(
        "SELECT id, status FROM approvals WHERE id = ?", (approval_id,)
    ).fetchone()

    if row is None:
        raise ApprovalNotFoundError(approval_id)
    if row["status"] == "superseded":
        raise ApprovalSupersededError(approval_id)
    if row["status"] != "pending":
        raise ApprovalNotGrantedError(approval_id, row["status"])

    decided_at = datetime.now(timezone.utc).isoformat()
    with db:
        db.execute(
            "UPDATE approvals SET status = 'rejected', decided_at = ? WHERE id = ? AND status = 'pending'",
            (decided_at, approval_id),
        )

    log_audit(
        db,
        actor="owner",
        event="approval_rejected",
        entity="approval",
        entity_id=approval_id,
        detail={"reason": reason, "decided_at": decided_at},
    )
    logger.info("Approval rejected — id=%s reason=%s", approval_id, reason)


# ── Edit and Supersede (SEC-06) ────────────────────────────────────────────────

def edit_and_supersede(
    approval_id: str,
    new_payload: dict[str, Any],
    db: sqlite3.Connection,
    new_target: Optional[str] = None,
    expiry_hours: int = _DEFAULT_EXPIRY_HOURS,
) -> str:
    """
    SEC-06: Edit-and-reapprove flow.
    Transitions previous approval to 'superseded' and creates a new pending proposal
    with supersedes_id set. The previous approval can never be executed.
    """
    row = db.execute(
        "SELECT id, action_type, status, target FROM approvals WHERE id = ?",
        (approval_id,),
    ).fetchone()

    if row is None:
        raise ApprovalNotFoundError(approval_id)
    if row["status"] not in ("pending", "approved"):
        raise ApprovalNotGrantedError(
            approval_id,
            f"Cannot edit approval in status '{row['status']}'",
        )

    action_type = row["action_type"]
    action_type, new_payload, target = normalize_action(action_type, new_payload, new_target)

    # SEC-08 Policy check
    policy = evaluate_target_policy(action_type, target, db)
    if not policy["allowed"]:
        raise SecurityPolicyViolationError(policy["reason"])

    new_id = str(uuid.uuid4())
    new_payload_json = json.dumps(new_payload, separators=(",", ":"), sort_keys=True)
    new_payload_hash = compute_payload_hash(action_type, new_payload, target)
    new_idempotency_key = f"idem_{new_id}"
    created_at = datetime.now(timezone.utc)
    expires_at = created_at + timedelta(hours=expiry_hours)

    with db:
        # 1. Supersede old approval
        db.execute(
            "UPDATE approvals SET status = 'superseded' WHERE id = ?",
            (approval_id,),
        )
        # 2. Insert new pending approval
        db.execute(
            """
            INSERT INTO approvals (
                id, action_type, payload_json, target, payload_hash,
                status, idempotency_key, supersedes_id, created_at, expires_at
            )
            VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)
            """,
            (
                new_id,
                action_type,
                new_payload_json,
                target,
                new_payload_hash,
                new_idempotency_key,
                approval_id,
                created_at.isoformat(),
                expires_at.isoformat(),
            ),
        )

    log_audit(
        db,
        actor="owner",
        event="approval_superseded",
        entity="approval",
        entity_id=approval_id,
        detail={"superseded_by": new_id},
    )
    log_audit(
        db,
        actor="owner",
        event="approval_requested",
        entity="approval",
        entity_id=new_id,
        detail={
            "supersedes": approval_id,
            "action_type": action_type,
            "target": target,
            "payload_hash": new_payload_hash,
            "idempotency_key": new_idempotency_key,
        },
    )

    logger.info("Approval %s superseded by new proposal %s", approval_id, new_id)
    return new_id


# ── Execute ────────────────────────────────────────────────────────────────────

def execute_approved(approval_id: str, db: sqlite3.Connection) -> None:
    """
    Execute the stored action for an approved record.

    SEC-01: takes NO payload argument. The payload is always loaded from the
    immutable DB row to prevent substitution attacks.

    SEC-02: verify canonical hash matches stored payload_hash and approved_hash.
    SEC-03: verify HMAC signature matches secret + approved_hash + decided_at.
    SEC-04: idempotency check prevents duplicate execution.
    SEC-05: only status='approved' can be executed (not expired, rejected, superseded).
    SEC-07: every execution attempt and outcome logged to audit_log.
    """
    row = db.execute(
        """
        SELECT id, action_type, payload_json, target, payload_hash, status,
               idempotency_key, approval_signature, approved_hash, decided_at, expires_at, source_agent
        FROM approvals
        WHERE id = ?
        """,
        (approval_id,),
    ).fetchone()

    if row is None:
        raise ApprovalNotFoundError(approval_id)

    status = row["status"]
    require_execution(db, row["source_agent"] or "orchestrator", row["action_type"])

    if status == "executed":
        raise ApprovalAlreadyExecutedError(approval_id)

    if status == "superseded":
        raise ApprovalSupersededError(approval_id)

    if status != "approved":
        raise ApprovalNotGrantedError(approval_id, status)

    # SEC-04 Idempotency Key check: verify no other row with same idempotency key was executed
    idempotency_key = row["idempotency_key"]
    if idempotency_key:
        executed_dup = db.execute(
            "SELECT id FROM approvals WHERE idempotency_key = ? AND status = 'executed' AND id != ?",
            (idempotency_key, approval_id),
        ).fetchone()
        if executed_dup:
            log_audit(
                db,
                actor="executor",
                event="idempotency_conflict_blocked",
                entity="approval",
                entity_id=approval_id,
                detail={"idempotency_key": idempotency_key, "already_executed_id": executed_dup["id"]},
            )
            raise IdempotencyConflictError(idempotency_key)

    # Check expiry (use UTC for comparison)
    if row["expires_at"]:
        expires_at = datetime.fromisoformat(row["expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expires_at:
            with db:
                db.execute(
                    "UPDATE approvals SET status = 'expired' WHERE id = ?", (approval_id,)
                )
            log_audit(
                db,
                actor="executor",
                event="approval_expired_rejected",
                entity="approval",
                entity_id=approval_id,
            )
            raise ApprovalExpiredError(approval_id)

    # SEC-02: Cryptographic payload hash integrity check
    recomputed_hash = compute_payload_hash(row["action_type"], row["payload_json"], row["target"])
    stored_hash = row["payload_hash"]
    approved_hash = row["approved_hash"]

    if recomputed_hash != stored_hash or (approved_hash and approved_hash != stored_hash):
        log_audit(
            db,
            actor="executor",
            event="payload_tampering_detected",
            entity="approval",
            entity_id=approval_id,
            detail={"recomputed": recomputed_hash, "stored": stored_hash, "approved": approved_hash},
        )
        raise ApprovalTamperedError(approval_id)

    # SEC-03: HMAC Signature verification (DB tamper-resistance)
    decided_at = row["decided_at"] or ""
    signature = row["approval_signature"]
    if not verify_approval_signature(approval_id, approved_hash or stored_hash, decided_at, signature):
        log_audit(
            db,
            actor="executor",
            event="hmac_signature_invalid",
            entity="approval",
            entity_id=approval_id,
            detail={"decided_at": decided_at},
        )
        raise ApprovalSignatureInvalidError(approval_id)

    # Atomic compare-and-set: transition approved → executing
    with db:
        cursor = db.execute(
            "UPDATE approvals SET status = 'executing' WHERE id = ? AND status = 'approved'",
            (approval_id,),
        )

    if cursor.rowcount == 0:
        # Another concurrent call won the race
        raise ApprovalClaimConflictError(approval_id)

    log_audit(
        db,
        actor="executor",
        event="execution_attempted",
        entity="approval",
        entity_id=approval_id,
        detail={"action_type": row["action_type"], "idempotency_key": idempotency_key},
    )
    logger.info("Execution claimed — id=%s action_type=%s", approval_id, row["action_type"])

    try:
        payload = json.loads(row["payload_json"])
        _dispatch_action(
            action_type=row["action_type"],
            payload=payload,
            approval_id=approval_id,
        )
    except Exception as exc:
        log_audit(
            db,
            actor="executor",
            event="execution_failed",
            entity="approval",
            entity_id=approval_id,
            detail={"error": str(exc)},
        )
        logger.exception("Dispatch failed for approval id=%s — row left in 'executing'", approval_id)
        raise

    # Transition executing → executed
    executed_at = datetime.now(timezone.utc).isoformat()
    with db:
        db.execute(
            "UPDATE approvals SET status = 'executed', executed_at = ? WHERE id = ?",
            (executed_at, approval_id),
        )

    log_audit(
        db,
        actor="executor",
        event="execution_succeeded",
        entity="approval",
        entity_id=approval_id,
        detail={"executed_at": executed_at, "idempotency_key": idempotency_key},
    )
    logger.info("Execution complete — id=%s executed_at=%s", approval_id, executed_at)


# ── Dispatch action (SDK_EXECUTOR) ─────────────────────────────────────────────
# This is the ONLY function in the codebase allowed to import email/publish SDKs.
# All SDK imports MUST be inside this function body, not at module level.
# Enforced by CI grep: `grep -r "smtplib\|hashnode\|devto" orchestrator_core/`
# must return only this file.

def _dispatch_action(
    action_type: str,
    payload: dict[str, Any],
    approval_id: str,
) -> None:
    """
    Execute the external action — email send or content publish.

    STUB: SDK calls are replaced with audit log entries until the
    real SDK integrations are wired in (post-Phase 4 sprint).

    Every invocation is fully auditable:
      - timestamp (UTC ISO)
      - action_type
      - payload_hash (SHA-256 of canonical JSON)
      - approval_id (traceability back to the DB row)

    # SDK_EXECUTOR: do not import email/publish SDKs elsewhere.
    """
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    payload_hash = hashlib.sha256(payload_json.encode()).hexdigest()[:16]
    timestamp = datetime.now(timezone.utc).isoformat()

    audit_record = {
        "timestamp": timestamp,
        "approval_id": approval_id,
        "action_type": action_type,
        "payload_hash": payload_hash,
        "status": "stub_executed",
    }

    logger.info("AUDIT | _dispatch_action | %s", json.dumps(audit_record))

    # Action dispatch branches
    if action_type == "send_email":
        import os
        from orchestrator_core.config import get_settings
        settings = get_settings()
        email_addr = os.getenv("EMAIL_ADDRESS") or settings.email_address
        email_pass = os.getenv("EMAIL_APP_PASSWORD") or settings.email_app_password
        to_email = payload.get("to_email") or payload.get("recipient") or payload.get("to")
        subject = payload.get("subject", "Orchestrator Notification")
        body = payload.get("body", "")

        is_test = bool(os.getenv("PYTEST_CURRENT_TEST"))
        enable_real = (
            os.getenv("ENABLE_REAL_EMAIL", "").lower() in ("true", "1")
            or getattr(settings, "enable_real_email", False)
        )
        # Block dummy or reserved test domains from real SMTP dispatch
        dummy_domains = ("example.com", "example.org", "example.net", "company.org", "test.com", "localhost")
        recipient_domain = str(to_email).split("@")[-1].lower() if "@" in str(to_email) else ""
        is_dummy_target = any(recipient_domain == d or recipient_domain.endswith("." + d) for d in dummy_domains)

        if not is_test and enable_real and not is_dummy_target and email_addr and email_pass and to_email and "your_email" not in str(email_addr):
            try:
                import smtplib
                from email.mime.text import MIMEText

                clean_to = str(to_email).strip()
                msg = MIMEText(body, "plain", "utf-8")
                msg["Subject"] = subject
                msg["From"] = email_addr
                msg["To"] = clean_to
                with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as server:
                    server.login(email_addr, email_pass)
                    server.send_message(msg)
                logger.info("Real SMTP sent email to %s via %s", clean_to, email_addr)
            except Exception as exc:
                logger.error("SMTP send attempt failed: %s", exc)
                raise RuntimeError(f"SMTP delivery failed: {exc}")
        else:
            logger.info(
                "Email action logged (safe simulation / stub mode). to=%s enable_real=%s is_test=%s is_dummy=%s payload_hash=%s",
                to_email,
                enable_real,
                is_test,
                is_dummy_target,
                payload_hash,
            )
    elif action_type == "publish_hashnode":
        logger.info("Executed publish_hashnode. payload_hash=%s", payload_hash)
    elif action_type == "publish_devto":
        logger.info("Executed publish_devto. payload_hash=%s", payload_hash)
    elif action_type == "github_create_issue":
        logger.info("Executed github_create_issue. payload_hash=%s", payload_hash)
    elif action_type == "github_comment":
        logger.info("Executed github_comment. payload_hash=%s", payload_hash)
    elif action_type == "linkedin_post":
        logger.info("Executed linkedin_post. payload_hash=%s", payload_hash)
    elif action_type == "linkedin_connect":
        logger.info("Executed linkedin_connect. payload_hash=%s", payload_hash)
    else:
        logger.warning("Unknown action_type=%r. payload_hash=%s", action_type, payload_hash)
