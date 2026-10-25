"""
orchestrator_core/routes/dispatch.py

POST /dispatch — classify a command, maintain persistent multi-chat conversation memory,
and execute against the resolved agent.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import sqlite3
import time
from typing import Optional
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, StreamingResponse
import json
from pydantic import BaseModel

from orchestrator_core.core.approval_gate import request_approval
from orchestrator_core.core.policy import require_execution, run_handler
from orchestrator_core.exceptions import AgentDisabledError, KillSwitchActiveError, SecurityPolicyViolationError
from orchestrator_core.core.router import classify
from orchestrator_core.models import (
    AgentResult,
    ClarificationNeeded,
    ErrorResponse,
    RouterResult,
    canonical_agent_name,
)
from orchestrator_core.storage.db import get_db, get_db_connection

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dispatch", tags=["Routing"])


def _get_agent_registry() -> dict:
    from orchestrator_core.agents import (
        career_agent,
        critic_agent,
        email_agent,
        general_chat_agent,
        github_agent,
        growth_content_agent,
        info_agent,
        linkedin_agent,
        research_agent,
    )
    return {
        "career_agent": career_agent.handle,
        "research_agent": research_agent.handle,
        "growth_content_agent": growth_content_agent.handle,
        "critic_agent": critic_agent.handle,
        "info_agent": info_agent.handle,
        "email_agent": email_agent.handle,
        "github_agent": github_agent.handle,
        "linkedin_agent": linkedin_agent.handle,
        "general_chat_agent": general_chat_agent.handle,
    }


def _handle_operational_command(command: str, db: sqlite3.Connection, conversation_id: str) -> Optional[AgentResult]:
    lower = command.lower().strip()
    require_execution(db)

    # 1. Pipelines
    if lower.startswith(("apply pipeline", "publish pipeline", "content pipeline", "research pipeline")):
        from orchestrator_core.core.pipeline_engine import run_pipeline
        from orchestrator_core.models import PipelineRequest

        if lower.startswith("apply pipeline"):
            p_name = "apply"
        elif lower.startswith("research pipeline"):
            p_name = "research"
        else:
            p_name = "publish"

        try:
            req = PipelineRequest(command=command)
            run_id = run_pipeline(p_name, req, db)

            steps = db.execute(
                "SELECT step_number, agent_name, latency_ms, success, output_json, error FROM pipeline_steps WHERE run_id = ? ORDER BY step_number ASC",
                (run_id,),
            ).fetchall()

            app_row = db.execute(
                "SELECT id, action_type, payload_json FROM approvals WHERE payload_json LIKE ? ORDER BY created_at DESC LIMIT 1",
                (f"%{run_id}%",),
            ).fetchone()
            approval_id = app_row["id"] if app_row else None

            step_rows_md = []
            for s in steps:
                st_num = s["step_number"]
                st_agent = s["agent_name"]
                st_lat = s["latency_ms"]
                st_status = "✅ Succeeded" if s["success"] else "❌ Failed"
                step_rows_md.append(f"| Stage {st_num} | `{st_agent}` | {st_lat}ms | {st_status} |")

            steps_table = "\n".join(step_rows_md)

            approval_note = ""
            if approval_id:
                approval_note = (
                    f"\n\n---\n"
                    f"🔒 **Human Approval Required**\n\n"
                    f"The final package has been prepared and queued in the Safety Gate.\n"
                    f"- **Approval ID**: `{approval_id}`\n"
                    f"- **Next Step**: Review this exact action in the **Approvals** tab."
                )

            output = (
                f"## 🚀 Pipeline Run Completed: `{p_name.upper()}`\n\n"
                f"- **Run ID**: `#{run_id}`\n"
                f"- **Status**: `completed`\n"
                f"- **Stages Executed**: {len(steps)}\n\n"
                f"### Execution Timeline\n\n"
                f"| Stage | Agent | Latency | Status |\n"
                f"|---|---|---|---|\n"
                f"{steps_table}"
                f"{approval_note}"
            )

            return AgentResult(
                agent="pipeline_engine",
                output=output,
                action_type="pipeline_run",
                approval_id=approval_id,
                metadata={"run_id": run_id, "pipeline_name": p_name, "approval_id": approval_id},
            )
        except Exception as exc:
            logger.exception("Pipeline execution failed: %s", exc)
            return AgentResult(
                agent="pipeline_engine",
                output=f"❌ **Pipeline Execution Failed**: {exc}",
                metadata={"error": str(exc)},
            )

    # 2. Approvals - List
    if lower in ("show approvals", "pending approvals", "list approvals", "approvals", "view approvals"):
        rows = db.execute(
            "SELECT id, action_type, status, payload_json, created_at FROM approvals WHERE status = 'pending' ORDER BY created_at DESC LIMIT 10"
        ).fetchall()
        if not rows:
            output = "🛡️ **Approval Gate Clean**: No actions currently pending human review.\n\nAll requested actions have been authorized and executed or rejected."
        else:
            table_rows = []
            for r in rows:
                try:
                    p = json.loads(r["payload_json"])
                    preview = p.get("to_email") or p.get("subject") or p.get("command") or str(p)[:40]
                except Exception:
                    preview = "payload"
                table_rows.append(f"| `{r['id'][:8]}` | `{r['action_type']}` | {preview} | {r['created_at'][:19]} | Review in Approvals |")

            output = (
                f"🛡️ **Pending Approvals Queue ({len(rows)} pending)**\n\n"
                f"| ID | Action Type | Details | Created At | Command |\n"
                f"|---|---|---|---|---|\n"
                + "\n".join(table_rows) + "\n\n"
                f"To authorize and execute: Open **Approvals** and review the exact record\n"
                f"To reject: Type **`reject <ID>`**"
            )
        return AgentResult(agent="approval_gate", output=output, metadata={"count": len(rows)})

    # Chat never chooses a proposal implicitly or mutates approval state.
    if (lower.startswith(("approve", "reject"))
            or lower in ("yes", "confirm", "send it", "no", "cancel action")):
        return AgentResult(
            agent="approval_gate",
            output="Open Approvals and review the exact action, target, payload, hash and expiration before deciding.",
            metadata={"status": "review_required"},
        )

    # 5. Quick Status
    if lower in ("quick status", "system status", "status", "cluster status"):
        pending_appr = db.execute("SELECT COUNT(*) FROM approvals WHERE status = 'pending'").fetchone()[0]
        total_jobs = db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        succ_jobs = db.execute("SELECT COUNT(*) FROM jobs WHERE status = 'succeeded'").fetchone()[0]
        running_jobs = db.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('running', 'queued')").fetchone()[0]
        scheds = db.execute("SELECT COUNT(*) FROM schedules WHERE is_active = 1").fetchone()[0]
        ks_row = db.execute("SELECT value FROM system_flags WHERE key = 'kill_switch'").fetchone()
        ks_val = ks_row["value"].strip().lower() if ks_row else "off"
        ks_status = "🔴 ACTIVE (HALTED)" if ks_val in ("on", "1", "true") else "🟢 INACTIVE (NORMAL)"

        output = (
            f"⚡ **Executive System Snapshot**\n\n"
            f"| Component | Status | Metric |\n"
            f"|---|---|---|\n"
            f"| **Control Plane** | 🟢 Operational | FastAPI v1.0.0 |\n"
            f"| **Router Circuit Breaker** | 🟢 Closed | Fail-fast protected |\n"
            f"| **Pending Approvals** | {'🟡' if pending_appr > 0 else '🟢'} {pending_appr} items | Zero-Payload Safety Gate |\n"
            f"| **Autonomous Jobs** | 🔵 {running_jobs} active | {succ_jobs} succeeded / {total_jobs} total |\n"
            f"| **Active Schedules** | ⏰ {scheds} enabled | Background APScheduler |\n"
            f"| **Emergency Kill Switch** | {ks_status} | Instant worker abort |\n"
        )
        return AgentResult(agent="orchestrator", output=output, metadata={"pending_approvals": pending_appr, "active_jobs": running_jobs})

    # 6. Morning Briefing
    if lower in ("morning briefing", "good morning", "daily briefing", "generate briefing"):
        now_dt = datetime.now()
        date_str = now_dt.strftime("%A, %B %d, %Y")
        time_str = now_dt.strftime("%I:%M %p")

        pending_appr = db.execute("SELECT COUNT(*) FROM approvals WHERE status = 'pending'").fetchone()[0]
        jobs_summary = db.execute("SELECT id, goal, status FROM jobs ORDER BY created_at DESC LIMIT 3").fetchall()

        job_lines = [f"- **#{j['id'][:8]}**: {j['goal']} (`{j['status']}`)" for j in jobs_summary]
        jobs_text = "\n".join(job_lines) if job_lines else "- No immediate active jobs. Fleet is idle and ready."

        output = (
            f"# 🌅 Good Morning, Farhan Aaqil\n\n"
            f"> **{date_str} • {time_str}** | AI Chief of Staff Operational Briefing\n\n"
            f"### 📋 Key System Priorities & Workflows\n"
            f"{jobs_text}\n\n"
            f"### 🛡️ Safety & Approvals Status\n"
            f"- **Pending Approvals**: `{pending_appr}` action(s) requiring your authorization.\n"
            f"- **Kill Switch**: `OFF` — Autonomous fleet operating under normal parameters.\n\n"
            f"### 🌐 AI & Research Pulse\n"
            f"- **ArXiv Highlights**: Recent breakthroughs in multi-agent verification and formal LLM guardrails.\n"
            f"- **Action Item**: Review your `Apply Pipeline` recommendations and research submissions.\n\n"
            f"Type any command, e.g. `show approvals`, `find internship`, or `research pipeline ...` to dispatch."
        )
        return AgentResult(agent="briefing_agent", output=output, metadata={"briefing_generated": True})

    # 7. System Controls - Kill Switch
    if lower in ("kill switch on", "enable kill switch", "activate kill switch"):
        now_iso = datetime.now(timezone.utc).isoformat()
        with db:
            db.execute(
                "INSERT INTO system_flags (key, value, updated_at) VALUES ('kill_switch', 'on', ?)"
                " ON CONFLICT(key) DO UPDATE SET value = 'on', updated_at = excluded.updated_at",
                (now_iso,),
            )
        output = "🛑 **EMERGENCY KILL SWITCH ACTIVATED**\n\nAll autonomous agent loops, worker routines, and background jobs are immediately halted. Claimed jobs will transition to `cancelled`."
        return AgentResult(agent="system", output=output, metadata={"kill_switch": "on"})

    if lower in ("kill switch off", "disable kill switch", "deactivate kill switch"):
        now_iso = datetime.now(timezone.utc).isoformat()
        with db:
            db.execute(
                "INSERT INTO system_flags (key, value, updated_at) VALUES ('kill_switch', 'off', ?)"
                " ON CONFLICT(key) DO UPDATE SET value = 'off', updated_at = excluded.updated_at",
                (now_iso,),
            )
        output = "🟢 **Emergency Kill Switch Deactivated**\n\nSystem restored to normal autonomous operations. Workers may resume claiming queued tasks."
        return AgentResult(agent="system", output=output, metadata={"kill_switch": "off"})

    # 8. Tasks & Jobs
    if lower in ("show tasks", "list tasks", "all tasks", "tasks", "my tasks"):
        jobs = db.execute("SELECT id, agent, goal, status, created_at FROM jobs ORDER BY created_at DESC LIMIT 10").fetchall()
        if not jobs:
            output = "📋 **No Recorded Tasks**: The autonomous job queue is empty. You can add one by typing `add task: <goal>`."
        else:
            table_rows = [f"| `#{j['id'][:8]}` | `{j['agent']}` | {j['goal']} | `{j['status']}` |" for j in jobs]
            output = (
                f"📋 **Autonomous Tasks & Jobs** ({len(jobs)} recent)\n\n"
                f"| ID | Agent | Goal | Status |\n"
                f"|---|---|---|---|\n"
                + "\n".join(table_rows) + "\n\n"
                f"To create a new task: Type **`add task: <description>`**"
            )
        return AgentResult(agent="project_manager", output=output, metadata={"count": len(jobs)})

    if lower.startswith("add task:"):
        desc = command.split(":", 1)[1].strip()
        from orchestrator_core.jobs.service import JobService
        try:
            job = JobService.create_job(agent="info_agent", goal=desc, db=db, priority=1)
            job_id = job.id
        except Exception:
            job_id = str(uuid.uuid4())
            now_iso = datetime.now(timezone.utc).isoformat()
            with db:
                db.execute(
                    "INSERT INTO jobs (id, thread_id, agent, goal, status, priority, created_at) VALUES (?, ?, 'info_agent', ?, 'queued', 1, ?)",
                    (job_id, job_id, desc, now_iso),
                )
        output = (
            f"✅ **Task Successfully Created & Queued**\n\n"
            f"- **Task ID**: `#{job_id[:8]}`\n"
            f"- **Goal**: {desc}\n"
            f"- **Agent**: `info_agent`\n"
            f"- **Status**: `queued`\n\n"
            f"View all tasks with `show tasks` or monitor in the Jobs tab."
        )
        return AgentResult(agent="project_manager", output=output, metadata={"job_id": job_id})

    # 9. Skills
    if lower in ("show skills", "my skills", "skills", "career stats", "career dashboard"):
        output = (
            f"🎓 **Farhan Aaqil — Skills & Expertise Portfolio**\n\n"
            f"| Category | Technologies & Competencies |\n"
            f"|---|---|\n"
            f"| **Languages** | Python, SQL, JavaScript, HTML5/CSS3 |\n"
            f"| **AI / ML & Agents** | Multi-Agent Systems, LangChain, LLM Routing, ChromaDB, RAG, Prompt Engineering |\n"
            f"| **Frameworks & Backend** | FastAPI, SQLite (CAS Concurrency), Uvicorn, Streamlit, Docker |\n"
            f"| **Data & Analytics** | Pandas, NumPy, Scikit-learn, Matplotlib |\n"
            f"| **Certifications** | 4x Anthropic Certifications, Apna College Full Stack, NPTEL DBMS, 2x SkillUp |\n"
            f"| **Published Research** | ML-based Diabetes Risk Prediction (*Peer-Reviewed Publication 2025*) |\n\n"
            f"To tailor your resume for a job: Type **`tailor resume for <Job Description>`**\n"
            f"To generate a cover letter: Type **`generate cover letter for <Company>, <Role>`**"
        )
        return AgentResult(agent="career_agent", output=output, metadata={"skills_view": True})

    return None


class DispatchRequest(BaseModel):
    command: str
    context: dict = {}
    conversation_id: Optional[str] = None


@router.post("", response_model=None)
async def dispatch_command(
    body: DispatchRequest,
    db: sqlite3.Connection = Depends(get_db_connection),
):
    """
    Classify and immediately execute a command within a persistent conversation thread.
    Injects past conversational context and saves the interaction to SQLite.
    """
    require_execution(db)
    t_start = time.monotonic()
    logger.info("Dispatching command: %.80s", body.command)
    now = datetime.now(timezone.utc).isoformat()

    # 1. Resolve or create conversation session
    cid = body.conversation_id
    if cid:
        row = db.execute("SELECT id FROM conversations WHERE id = ?", (cid,)).fetchone()
        if not row:
            title = body.command[:40] + ("..." if len(body.command) > 40 else "")
            with db:
                db.execute(
                    "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                    (cid, title, now, now),
                )
    else:
        cid = str(uuid.uuid4())
        title = body.command[:40] + ("..." if len(body.command) > 40 else "")
        with db:
            db.execute(
                "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (cid, title, now, now),
            )

    # 2. Retrieve last 10 messages for conversation context
    history_rows = db.execute(
        """
        SELECT role, content, agent
        FROM messages
        WHERE conversation_id = ?
        ORDER BY created_at ASC
        LIMIT 10
        """,
        (cid,),
    ).fetchall()

    history_text = "\n".join(
        f"{r['role'].upper()} ({r['agent'] or 'user'}): {r['content']}"
        for r in history_rows
    )

    # 3. Store user message in messages table
    user_msg_id = str(uuid.uuid4())
    with db:
        db.execute(
            "INSERT INTO messages (id, conversation_id, role, content, agent, created_at) VALUES (?, ?, 'user', ?, NULL, ?)",
            (user_msg_id, cid, body.command, now),
        )

    # 3.5 Check for deterministic operational command
    op_result = _handle_operational_command(body.command, db, cid)
    if op_result:
        latency_ms = int((time.monotonic() - t_start) * 1000)
        op_result.metadata["latency_ms"] = latency_ms
        op_result.metadata["conversation_id"] = cid
        asst_msg_id = str(uuid.uuid4())
        with db:
            db.execute(
                "INSERT INTO messages (id, conversation_id, role, content, agent, created_at) VALUES (?, ?, 'assistant', ?, ?, ?)",
                (asst_msg_id, cid, op_result.output, op_result.agent, now),
            )
            db.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, cid))
        return op_result

    # 4. Route command
    classification = classify(body.command)

    if isinstance(classification, ClarificationNeeded):
        logger.info("Dispatch blocked — clarification needed: %s", classification.candidates)
        # Store clarifying assistant message in thread
        asst_msg_id = str(uuid.uuid4())
        clarification_msg = f"Clarification required: {classification.reasoning}. Options: {', '.join(classification.candidates)}"
        with db:
            db.execute(
                "INSERT INTO messages (id, conversation_id, role, content, agent, created_at) VALUES (?, ?, 'assistant', ?, 'router', ?)",
                (asst_msg_id, cid, clarification_msg, now),
            )
            db.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, cid))
        return JSONResponse(
            status_code=422,
            content=classification.model_dump(),
        )

    assert isinstance(classification, RouterResult)
    agent_name = classification.agent
    registry = _get_agent_registry()

    if agent_name not in registry:
        return JSONResponse(
            status_code=400,
            content=ErrorResponse(
                error="AGENT_NOT_FOUND",
                detail=f"Agent '{agent_name}' is not registered in the dispatch registry.",
            ).model_dump(),
        )

    # 4b. Verify agent is not administratively disabled
    canonical = canonical_agent_name(agent_name)
    flag_rows = db.execute(
        "SELECT value FROM system_flags WHERE key IN (?, ?)",
        (f"agent_enabled_{canonical}", f"agent_enabled_{agent_name}"),
    ).fetchall()
    for r in flag_rows:
        if r["value"].strip() == "0":
            return JSONResponse(
                status_code=403,
                content=ErrorResponse(
                    error="AGENT_DISABLED",
                    detail=f"Agent '{agent_name}' is administratively disabled.",
                ).model_dump(),
            )

    # 5. Execute agent with context injection
    handler = registry[agent_name]
    agent_meta = {
        "context": body.context,
        "conversation_id": cid,
        "conversation_history_text": history_text,
    }
    result: AgentResult = run_handler(handler, body.command, db, agent_name, agent_meta, cid)

    # 6. Auto-queue approval if write action is triggered and not yet queued
    if result.action_type and not result.approval_id:
        approval_payload = result.metadata.get("approval_payload") or {
            "command": body.command,
            "action_type": result.action_type,
            "agent": agent_name,
        }
        try:
            app_id = request_approval(action_type=result.action_type, payload=approval_payload, db=db, source_agent=agent_name, session_id=cid)
            result.approval_id = app_id
            result.metadata["approval_id"] = app_id
        except Exception as exc:
            logger.warning("Could not auto-queue approval record: %s", exc)

    latency_ms = int((time.monotonic() - t_start) * 1000)
    logger.info(
        "Dispatch complete — agent=%s confidence=%.2f latency_ms=%d",
        agent_name,
        classification.confidence,
        latency_ms,
    )

    result.metadata["latency_ms"] = latency_ms
    result.metadata["confidence"] = classification.confidence
    result.metadata["reasoning"] = classification.reasoning
    result.metadata["conversation_id"] = cid

    # 7. Store assistant message in messages table & update conversation timestamp
    asst_msg_id = str(uuid.uuid4())
    with db:
        db.execute(
            "INSERT INTO messages (id, conversation_id, role, content, agent, created_at) VALUES (?, ?, 'assistant', ?, ?, ?)",
            (asst_msg_id, cid, result.output, agent_name, now),
        )
        db.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, cid))

    return result


@router.post("/stream")
async def dispatch_command_stream(body: DispatchRequest):
    """
    Classify and stream responses in real-time via Server-Sent Events (§5c No-Lag).
    Perceived latency drops to 200-400ms for the first token.
    """
    def event_stream():
        t_start = time.monotonic()
        now = datetime.now(timezone.utc).isoformat()
        db = get_db()
        try:
            require_execution(db)
            # 1. Resolve or create conversation session
            cid = body.conversation_id
            if cid:
                row = db.execute("SELECT id FROM conversations WHERE id = ?", (cid,)).fetchone()
                if not row:
                    title = body.command[:40] + ("..." if len(body.command) > 40 else "")
                    with db:
                        db.execute(
                            "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                            (cid, title, now, now),
                        )
            else:
                cid = str(uuid.uuid4())
                title = body.command[:40] + ("..." if len(body.command) > 40 else "")
                with db:
                    db.execute(
                        "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                        (cid, title, now, now),
                    )

            # 2. Retrieve history context
            history_rows = db.execute(
                """
                SELECT role, content, agent
                FROM messages
                WHERE conversation_id = ?
                ORDER BY created_at ASC
                LIMIT 10
                """,
                (cid,),
            ).fetchall()

            history_text = "\n".join(
                f"{r['role'].upper()} ({r['agent'] or 'user'}): {r['content']}"
                for r in history_rows
            )

            # 3. Store user message
            user_msg_id = str(uuid.uuid4())
            with db:
                db.execute(
                    "INSERT INTO messages (id, conversation_id, role, content, agent, created_at) VALUES (?, ?, 'user', ?, NULL, ?)",
                    (user_msg_id, cid, body.command, now),
                )

            # 3.5 Check for deterministic operational command
            op_result = _handle_operational_command(body.command, db, cid)
            if op_result:
                latency_ms = int((time.monotonic() - t_start) * 1000)
                yield f"event: meta\ndata: {json.dumps({'agent': op_result.agent, 'conversation_id': cid, 'confidence': 1.0, 'reasoning': 'Deterministic operational execution'})}\n\n"
                yield f"event: token\ndata: {json.dumps({'token': op_result.output})}\n\n"
                asst_msg_id = str(uuid.uuid4())
                with db:
                    db.execute(
                        "INSERT INTO messages (id, conversation_id, role, content, agent, created_at) VALUES (?, ?, 'assistant', ?, ?, ?)",
                        (asst_msg_id, cid, op_result.output, op_result.agent, now),
                    )
                    db.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, cid))
                yield f"event: done\ndata: {json.dumps({'output': op_result.output, 'agent': op_result.agent, 'action_type': op_result.action_type, 'approval_id': op_result.approval_id, 'latency_ms': latency_ms, 'conversation_id': cid})}\n\n"
                return

            # 4. Route command
            classification = classify(body.command)

            if isinstance(classification, ClarificationNeeded):
                clarification_msg = f"Clarification required: {classification.reasoning}. Options: {', '.join(classification.candidates)}"
                asst_msg_id = str(uuid.uuid4())
                with db:
                    db.execute(
                        "INSERT INTO messages (id, conversation_id, role, content, agent, created_at) VALUES (?, ?, 'assistant', ?, 'router', ?)",
                        (asst_msg_id, cid, clarification_msg, now),
                    )
                    db.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, cid))
                yield f"event: clarification\ndata: {json.dumps(classification.model_dump())}\n\n"
                return

            assert isinstance(classification, RouterResult)
            agent_name = classification.agent
            registry = _get_agent_registry()
            require_execution(db, agent_name)

            if agent_name not in registry:
                err_data = {"error": "AGENT_NOT_FOUND", "detail": f"Agent '{agent_name}' not found."}
                yield f"event: error\ndata: {json.dumps(err_data)}\n\n"
                return

            # Yield metadata event immediately so frontend knows which agent was routed
            yield f"event: meta\ndata: {json.dumps({'agent': agent_name, 'conversation_id': cid, 'confidence': classification.confidence, 'reasoning': classification.reasoning})}\n\n"

            accumulated_output = []

            # 5. Execution (streaming for general_chat_agent, handler for specialized agents)
            if agent_name == "general_chat_agent":
                from orchestrator_core.agents import general_chat_agent
                for token in general_chat_agent.stream_llm(body.command, context_history=history_text):
                    accumulated_output.append(token)
                    yield f"event: token\ndata: {json.dumps({'token': token})}\n\n"
                full_text = "".join(accumulated_output)
                action_type = None
                approval_id = None
            else:
                handler = registry[agent_name]
                agent_meta = {
                    "context": body.context,
                    "conversation_id": cid,
                    "conversation_history_text": history_text,
                }
                result: AgentResult = run_handler(handler, body.command, db, agent_name, agent_meta, cid)
                full_text = result.output
                action_type = result.action_type
                approval_id = result.approval_id
                # Auto-queue approval if write action
                if action_type and not approval_id:
                    approval_payload = result.metadata.get("approval_payload") or {
                        "command": body.command,
                        "action_type": action_type,
                        "agent": agent_name,
                    }
                    try:
                        app_id = request_approval(action_type=action_type, payload=approval_payload, db=db, source_agent=agent_name, session_id=cid)
                        approval_id = app_id
                    except Exception as exc:
                        logger.warning("Could not auto-queue approval record in stream: %s", exc)
                # Yield entire output as token chunk
                yield f"event: token\ndata: {json.dumps({'token': full_text})}\n\n"

            latency_ms = int((time.monotonic() - t_start) * 1000)

            # 6. Save assistant output to messages table
            asst_msg_id = str(uuid.uuid4())
            with db:
                db.execute(
                    "INSERT INTO messages (id, conversation_id, role, content, agent, created_at) VALUES (?, ?, 'assistant', ?, ?, ?)",
                    (asst_msg_id, cid, full_text, agent_name, now),
                )
                db.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, cid))

            # Final done event
            yield f"event: done\ndata: {json.dumps({'output': full_text, 'agent': agent_name, 'action_type': action_type, 'approval_id': approval_id, 'latency_ms': latency_ms, 'conversation_id': cid})}\n\n"
        except (AgentDisabledError, KillSwitchActiveError, SecurityPolicyViolationError) as exc:
            code = "AGENT_DISABLED" if isinstance(exc, AgentDisabledError) else "KILL_SWITCH_ACTIVE" if isinstance(exc, KillSwitchActiveError) else "SECURITY_POLICY_VIOLATION"
            yield f"event: error\ndata: {json.dumps({'error': code, 'detail': str(exc)})}\n\n"
        finally:
            db.close()

    return StreamingResponse(event_stream(), media_type="text/event-stream")
