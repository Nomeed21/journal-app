"""Quiet, read-only summaries and explicit task organization. No new tables."""
from datetime import date, datetime, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from backend.db import supabase
from backend import journal_store
from backend.core.time_utils import local_date_today, local_date_from_iso

router = APIRouter(prefix="/calm")
ABSENCE_DAYS = 7


def return_state(entries, today):
    meaningful = [e for e in entries if "__skipped__" not in (e.get("tags") or [])]
    last = max((local_date_from_iso(e["created_at"]) for e in meaningful), default=None)
    gap = (date.fromisoformat(today) - date.fromisoformat(last)).days if last else 0
    return {"new_user": last is None, "last_entry_date": last,
            "welcome_back": last is not None and gap >= ABSENCE_DAYS,
            "absence_threshold_days": ABSENCE_DAYS, "today": today}


@router.get("/summary")
def summary():
    counts = journal_store.participation()
    latest = counts.pop("latest")
    previous = [{"created_at": latest}] if latest else []
    return {**return_state(previous, local_date_today()), **counts,
            "counts_scope": "all records", "ai_enabled": False, "storage": "local SQLite"}


@router.get("/streak")
def streak():
    return journal_store.journal_streak(local_date_today())


@router.get("/journal")
def journal(offset: int = 0):
    if offset < 0:
        raise HTTPException(422, "Invalid page")
    return journal_store.records(offset=offset, limit=50)


@router.get("/tasks")
def tasks(offset: int = 0):
    if offset < 0:
        raise HTTPException(422, "Invalid page")
    return supabase.table("board_quests").select("id,title,section,due_date,is_completed,created_at").order("created_at", desc=True).order("id", desc=True).range(offset, offset + 49).execute().data


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)


@router.post("/tasks")
def create_task(task: TaskCreate):
    title = task.title.strip()
    if not title:
        raise HTTPException(422, "Write a task first")
    return supabase.table("board_quests").insert({"title": title, "section": "weekly",
        "source_type": "manual", "source_id": "manual:" + datetime.now(timezone.utc).isoformat(),
        "is_completed": False, "due_date": None}).execute().data[0]


class TaskPlacement(BaseModel):
    section: str
    due_date: Optional[date] = None


@router.put("/tasks/{task_id}/placement")
def place_task(task_id: int, placement: TaskPlacement):
    if placement.section not in {"recommended", "daily", "weekly", "skill", "recovery", "boss", "completed", "archived"}:
        raise HTTPException(422, "Unknown task section")
    rows = supabase.table("board_quests").select("section,due_date").eq("id", task_id).execute().data
    if not rows:
        raise HTTPException(404, "Task not found")
    data = {"section": placement.section, "due_date": placement.due_date.isoformat() if placement.due_date else None}
    result = supabase.table("board_quests").update(data).eq("id", task_id).execute().data
    # Preserve completion and history; the previous placement enables explicit undo.
    from backend.main import _invalidate_board_cache
    _invalidate_board_cache()
    return {"task": result[0], "previous": rows[0]}
