"""
orchestrator_core/routes/schedules.py

HTTP endpoints for managing recurring autonomous schedules (Phase 8).
Supports listing, creating, toggling, cron modifications, deletion, and immediate run triggers.
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from orchestrator_core.dependencies import verify_bearer_token
from orchestrator_core.jobs.service import JobService
from orchestrator_core.storage.db import get_db_connection, log_audit

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/schedules", tags=["Schedules"])


class ScheduleRecord(BaseModel):
    id: str
    name: str
    agent: str
    goal: str
    cron_expr: str
    is_active: bool
    last_run_at: Optional[str] = None
    next_run_at: Optional[str] = None
    created_at: str
    updated_at: str


class ScheduleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    agent: str = Field(min_length=1, max_length=50)
    goal: str = Field(min_length=1)
    cron_expr: str = Field(default="0 8 * * *", min_length=1)
    is_active: bool = True


class ScheduleUpdate(BaseModel):
    name: Optional[str] = None
    agent: Optional[str] = None
    goal: Optional[str] = None
    cron_expr: Optional[str] = None
    is_active: Optional[bool] = None


def _row_to_schedule(row: sqlite3.Row) -> ScheduleRecord:
    d = dict(row)
    return ScheduleRecord(
        id=d["id"],
        name=d["name"],
        agent=d["agent"],
        goal=d["goal"],
        cron_expr=d["cron_expr"],
        is_active=bool(d["is_active"]),
        last_run_at=d["last_run_at"],
        next_run_at=d["next_run_at"],
        created_at=d["created_at"],
        updated_at=d["updated_at"],
    )


@router.get("", response_model=list[ScheduleRecord])
async def list_schedules(
    db: sqlite3.Connection = Depends(get_db_connection),
    _token: Optional[str] = Depends(verify_bearer_token),
):
    """List all configured autonomous schedules."""
    rows = db.execute("SELECT * FROM schedules ORDER BY created_at ASC").fetchall()
    return [_row_to_schedule(r) for r in rows]


@router.post("", response_model=ScheduleRecord, status_code=status.HTTP_201_CREATED)
async def create_schedule(
    body: ScheduleCreate,
    db: sqlite3.Connection = Depends(get_db_connection),
    _token: Optional[str] = Depends(verify_bearer_token),
):
    """Create a new recurring schedule."""
    schedule_id = f"sched_{uuid.uuid4().hex[:10]}"
    now = datetime.now(timezone.utc).isoformat()

    with db:
        db.execute(
            """
            INSERT INTO schedules (id, name, agent, goal, cron_expr, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                schedule_id,
                body.name,
                body.agent,
                body.goal,
                body.cron_expr,
                1 if body.is_active else 0,
                now,
                now,
            ),
        )

    log_audit(
        db,
        actor="admin",
        event="schedule_created",
        entity="schedule",
        entity_id=schedule_id,
        detail={"name": body.name, "agent": body.agent, "cron_expr": body.cron_expr},
    )

    row = db.execute("SELECT * FROM schedules WHERE id = ?", (schedule_id,)).fetchone()
    return _row_to_schedule(row)


@router.get("/{schedule_id}", response_model=ScheduleRecord)
async def get_schedule(
    schedule_id: str,
    db: sqlite3.Connection = Depends(get_db_connection),
    _token: Optional[str] = Depends(verify_bearer_token),
):
    """Retrieve schedule details by ID."""
    row = db.execute("SELECT * FROM schedules WHERE id = ?", (schedule_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Schedule '{schedule_id}' not found")
    return _row_to_schedule(row)


@router.patch("/{schedule_id}", response_model=ScheduleRecord)
async def update_schedule(
    schedule_id: str,
    body: ScheduleUpdate,
    db: sqlite3.Connection = Depends(get_db_connection),
    _token: Optional[str] = Depends(verify_bearer_token),
):
    """Update schedule properties or active state."""
    row = db.execute("SELECT * FROM schedules WHERE id = ?", (schedule_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Schedule '{schedule_id}' not found")

    updates = []
    params = []
    now = datetime.now(timezone.utc).isoformat()

    if body.name is not None:
        updates.append("name = ?")
        params.append(body.name)
    if body.agent is not None:
        updates.append("agent = ?")
        params.append(body.agent)
    if body.goal is not None:
        updates.append("goal = ?")
        params.append(body.goal)
    if body.cron_expr is not None:
        updates.append("cron_expr = ?")
        params.append(body.cron_expr)
    if body.is_active is not None:
        updates.append("is_active = ?")
        params.append(1 if body.is_active else 0)

    if not updates:
        return _row_to_schedule(row)

    updates.append("updated_at = ?")
    params.append(now)
    params.append(schedule_id)

    with db:
        db.execute(f"UPDATE schedules SET {', '.join(updates)} WHERE id = ?", params)

    updated_row = db.execute("SELECT * FROM schedules WHERE id = ?", (schedule_id,)).fetchone()
    return _row_to_schedule(updated_row)


@router.delete("/{schedule_id}")
async def delete_schedule(
    schedule_id: str,
    db: sqlite3.Connection = Depends(get_db_connection),
    _token: Optional[str] = Depends(verify_bearer_token),
):
    """Delete a schedule."""
    with db:
        cur = db.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Schedule '{schedule_id}' not found")

    log_audit(
        db,
        actor="admin",
        event="schedule_deleted",
        entity="schedule",
        entity_id=schedule_id,
    )
    return {"deleted": True, "id": schedule_id}


@router.post("/{schedule_id}/run")
async def run_schedule_now(
    schedule_id: str,
    db: sqlite3.Connection = Depends(get_db_connection),
    _token: Optional[str] = Depends(verify_bearer_token),
):
    """Trigger immediate execution of a schedule by enqueueing an autonomous job."""
    row = db.execute("SELECT * FROM schedules WHERE id = ?", (schedule_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Schedule '{schedule_id}' not found")

    schedule = _row_to_schedule(row)
    now = datetime.now(timezone.utc).isoformat()

    job = JobService.create_job(
        agent=schedule.agent,
        goal=f"[Scheduled: {schedule.name}] {schedule.goal}",
        db=db,
        schedule_id=schedule.id,
    )

    with db:
        db.execute("UPDATE schedules SET last_run_at = ?, updated_at = ? WHERE id = ?", (now, now, schedule_id))

    log_audit(
        db,
        actor="admin",
        event="schedule_triggered_manually",
        entity="schedule",
        entity_id=schedule_id,
        detail={"job_id": job.id},
    )

    return {
        "status": "triggered",
        "schedule_id": schedule_id,
        "job_id": job.id,
        "agent": schedule.agent,
        "goal": job.goal,
    }
