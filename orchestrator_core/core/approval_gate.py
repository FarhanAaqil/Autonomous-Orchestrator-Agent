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
import inspect
from functools import wraps
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
    context: str = "",
) -> str:
    """
    HMAC-SHA256 signature over (approval_id, approved_hash, decided_at).
    SEC-03: Signed with EXECUTOR_HMAC_SECRET. DB tampering by agents/tools cannot forge this.
    """
    if secret is None:
        secret = get_settings().executor_hmac_secret
    message = f"{approval_id}:{approved_hash}:{decided_at}:{context}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def verify_approval_signature(
    approval_id: str,
    approved_hash: str,
    decided_at: str,
    signature: Optional[str],
    secret: Optional[str] = None,
    context: str = "",
) -> bool:
    """Verify HMAC signature against expected secret."""
    if not signature:
        return False
    expected = generate_approval_signature(approval_id, approved_hash, decided_at, secret, context)
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
        "SELECT 1 FROM approvals WHERE target = ? AND status = 'confirmed' LIMIT 1",
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

def atomic_decision(fn):
    """Serialize decision reads and writes; audit inserts join this transaction."""
    @wraps(fn)
    def wrapped(*args, **kwargs):
        db = inspect.signature(fn).bind(*args, **kwargs).arguments["db"]
        if db.in_transaction:
            raise RuntimeError("Approval decisions require a clean transaction boundary.")
        db.execute("BEGIN IMMEDIATE")
        try:
            result = fn(*args, **kwargs)
            db.commit()
            return result
        except BaseException:
            db.rollback()
            raise
    return wrapped


@atomic_decision
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
            "SELECT * FROM approvals WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if existing:
            if (existing["status"] not in ("pending", "approved")
                    or existing["payload_hash"] != compute_payload_hash(action_type, payload, target)
                    or existing["source_agent"] != source_agent or existing["session_id"] != session_id):
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

def _consent_context(row) -> str:
    return json.dumps([row["source_agent"], row["session_id"], row["expires_at"]], separators=(",", ":"))


@atomic_decision
def approve(
    approval_id: str,
    db: sqlite3.Connection,
    expected_hash: Optional[str] = None,
    session_id: Optional[str] = None,
) -> None:
    """
    Transition a pending approval to 'approved' state.
    SEC-02: Verifies current DB payload hash matches stored hash.
    TOCTOU: If expected_hash is provided, verifies displayed hash matches DB hash.
    SEC-03: Computes and persists HMAC signature with server secret.
    """
    row = db.execute(
        "SELECT * FROM approvals WHERE id = ?",
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
    if not expected_hash or expected_hash != stored_hash:
        raise ApprovalHashMismatchError(approval_id, expected_hash, stored_hash)

    if session_id != row["session_id"]:
        raise SecurityPolicyViolationError("Review belongs to a different conversation.")
    if not row["expires_at"] or datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc):
        raise ApprovalExpiredError(approval_id)

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
    signature = generate_approval_signature(approval_id, approved_hash, decided_at, context=_consent_context(row))

    db.execute(
        """
        UPDATE approvals
        SET status = 'approved', version = version + 1,
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


@atomic_decision
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
    db.execute(
        "UPDATE approvals SET status = 'rejected', version = version + 1, decided_at = ? WHERE id = ? AND status = 'pending'",
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

@atomic_decision
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
        "SELECT * FROM approvals WHERE id = ?",
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

    # 1. Supersede old approval
    db.execute(
        "UPDATE approvals SET status = 'superseded', version = version + 1 WHERE id = ? AND status IN ('pending', 'approved')",
        (approval_id,),
    )
    # 2. Insert new pending approval
    db.execute(
        """
        INSERT INTO approvals (
            id, action_type, payload_json, target, payload_hash,
            status, idempotency_key, supersedes_id, created_at, expires_at, source_agent, session_id
        )
        VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?)
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
            row["source_agent"],
            row["session_id"],
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

def _transition(db, row, status, event, **fields):
    fields.update(status=status, version=row["version"] + 1)
    assignments = ", ".join(f"{key}=?" for key in fields)
    with db:
        changed = db.execute(
            f"UPDATE approvals SET {assignments} WHERE id=? AND status=? AND version=?",
            (*fields.values(), row["id"], row["status"], row["version"]),
        )
        if changed.rowcount != 1:
            raise ApprovalClaimConflictError(row["id"])
        log_audit(db, actor="executor", event=event, entity_id=row["id"], detail={"status": status})


def execute_approved(approval_id: str, db: sqlite3.Connection) -> dict:
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
               idempotency_key, approval_signature, approved_hash, decided_at, expires_at, source_agent, session_id, version
        FROM approvals
        WHERE id = ?
        """,
        (approval_id,),
    ).fetchone()

    if row is None:
        raise ApprovalNotFoundError(approval_id)

    status = row["status"]
    require_execution(db, row["source_agent"] or "orchestrator", row["action_type"])

    if status in ("executed", "simulated", "submitted", "confirmed", "failed", "outcome_unknown"):
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
            _transition(db, row, "expired", "approval_expired_rejected")
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
    if not verify_approval_signature(approval_id, approved_hash or stored_hash, decided_at, signature, context=_consent_context(row)):
        log_audit(
            db,
            actor="executor",
            event="hmac_signature_invalid",
            entity="approval",
            entity_id=approval_id,
            detail={"decided_at": decided_at},
        )
        raise ApprovalSignatureInvalidError(approval_id)

    attempt_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc).isoformat()
    with db:
        changed = db.execute(
            "UPDATE approvals SET status='executing', version=version+1 WHERE id=? AND status='approved' AND version=?",
            (approval_id, row["version"]),
        )
        if changed.rowcount != 1:
            raise ApprovalClaimConflictError(approval_id)
        db.execute(
            "INSERT INTO execution_attempts (id,approval_id,provider_key,outcome,started_at) VALUES (?,?,?,'outcome_unknown',?)",
            (attempt_id, approval_id, row["idempotency_key"], started_at),
        )
        log_audit(db, actor="executor", event="execution_attempted", entity_id=approval_id,
                  detail={"attempt_id": attempt_id, "provider_key": row["idempotency_key"]})

    try:
        result = _dispatch_action(row["action_type"], json.loads(row["payload_json"]), approval_id)
        if not isinstance(result, dict) or result.get("outcome") not in ("simulated", "submitted", "confirmed", "failed", "outcome_unknown"):
            raise RuntimeError("Adapter returned no valid execution outcome")
    except Exception as exc:
        # Once dispatch has begun, an unclassified failure cannot prove no effect.
        result = {"outcome": "outcome_unknown", "error_class": type(exc).__name__}
    finished_at = datetime.now(timezone.utc).isoformat()
    with db:
        changed = db.execute(
            "UPDATE approvals SET status=?, executed_at=?, version=version+1 WHERE id=? AND status='executing' AND version=?",
            (result["outcome"], finished_at, approval_id, row["version"] + 1),
        )
        if changed.rowcount != 1:
            raise ApprovalClaimConflictError(approval_id)
        db.execute(
            "UPDATE execution_attempts SET outcome=?, finished_at=?, receipt_json=?, error_class=? WHERE id=?",
            (result["outcome"], finished_at, json.dumps(result.get("receipt", {})), result.get("error_class"), attempt_id),
        )
        log_audit(db, actor="executor", event="execution_outcome", entity_id=approval_id, detail=result)
    return {"approval_id": approval_id, "attempt_id": attempt_id, "status": result["outcome"], **result}


@atomic_decision
def reconcile_execution(approval_id, outcome, evidence, db):
    """Owner records independently verified evidence; never resends an action."""
    if outcome not in ("confirmed", "failed") or len(evidence.strip()) < 10:
        raise SecurityPolicyViolationError("Reconciliation requires confirmed/failed and specific provider evidence.")
    row = db.execute("SELECT * FROM execution_attempts WHERE approval_id=?", (approval_id,)).fetchone()
    if row is None or row["outcome"] not in ("submitted", "outcome_unknown"):
        raise SecurityPolicyViolationError("Only submitted or uncertain attempts can be reconciled.")
    if row["finished_at"] is None:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(row["started_at"])
        if age.total_seconds() < 300:
            raise SecurityPolicyViolationError("The execution may still be active; wait at least five minutes.")
    now = datetime.now(timezone.utc).isoformat()
    changed = db.execute(
        "UPDATE approvals SET status=?, version=version+1 WHERE id=? AND status IN ('executing','submitted','outcome_unknown')",
        (outcome, approval_id),
    )
    if changed.rowcount != 1:
        raise ApprovalClaimConflictError(approval_id)
    db.execute("UPDATE execution_attempts SET outcome=?, finished_at=?, receipt_json=? WHERE approval_id=?",
               (outcome, now, json.dumps({"owner_evidence": evidence}), approval_id))
    log_audit(db, actor="owner", event="execution_reconciled", entity_id=approval_id,
              detail={"outcome": outcome, "evidence": evidence})
    return {"approval_id": approval_id, "status": outcome}



def _dispatch_action(action_type: str, payload: dict[str, Any], approval_id: str) -> dict:
    """SDK_EXECUTOR: report SMTP acceptance, never infer inbox delivery."""
    require_adapter(action_type)
    action_type, payload, _ = normalize_action(action_type, payload)
    settings = get_settings()
    if settings.action_execution_mode == "disabled":
        return {"outcome": "failed", "error_class": "ExecutionDisabled"}
    if settings.action_execution_mode == "simulation":
        return {"outcome": "simulated", "receipt": {"mode": "simulation", "external_effect": False}}
    if not (settings.enable_real_email and settings.email_address and settings.email_app_password):
        return {"outcome": "failed", "error_class": "MissingCredentials"}
    import smtplib
    from email.mime.text import MIMEText

    msg = MIMEText(payload["body"], "plain", "utf-8")
    msg["Subject"] = payload["subject"]
    msg["From"] = settings.email_address
    msg["To"] = payload["to_email"]
    # Stable correlation identifier. SMTP does NOT promise deduplication for it.
    msg["Message-ID"] = f"<{approval_id}@orchestrator.local>"
    server = None
    try:
        server = smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20)
        server.login(settings.email_address, settings.email_app_password)
    except Exception as exc:
        if server is not None:
            server.close()
        return {"outcome": "failed", "error_class": type(exc).__name__}
    try:
        refused = server.send_message(msg)
        if refused:
            return {"outcome": "failed", "error_class": "RecipientRefused"}
        return {"outcome": "submitted", "receipt": {"message_id": msg["Message-ID"], "provider": "smtp.gmail.com"}}
    except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused, smtplib.SMTPDataError) as exc:
        return {"outcome": "failed", "error_class": type(exc).__name__}
    except Exception as exc:
        return {"outcome": "outcome_unknown", "error_class": type(exc).__name__}
    finally:
        # A failure to close cannot change the provider acceptance already observed.
        try:
            server.close()
        except Exception:
            logger.warning("SMTP connection cleanup failed")
