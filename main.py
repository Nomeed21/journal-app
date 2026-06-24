import os
import json as _json
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager
from collections import defaultdict
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer
from supabase import create_client
from groq import Groq

load_dotenv()

embedding_model = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global embedding_model
    embedding_model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    yield


app = FastAPI(lifespan=lifespan)

supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

XP_PER_TASK      = 50
XP_PER_LEVEL     = 500
RECENT_DAYS      = 14
MAX_WEEKLY_ROWS  = 26

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class EntryCreate(BaseModel):
    title: str
    content: str
    mood: int
    goal_progress: int
    tags: list[str] = []
    entry_type: str = "free"
    energy: int = 3
    focus: int = 3

class ChatTurn(BaseModel):
    role: str
    content: str

class ChatMessage(BaseModel):
    message: str
    history: list[ChatTurn] = []

class HabitLog(BaseModel):
    name: str

class GoalCreate(BaseModel):
    title: str
    category: str

class TaskCreate(BaseModel):
    title: str

class ActionEngineRequest(BaseModel):
    mood: int
    goal_progress: int
    content: str
    energy: int = 3
    focus: int = 3
    entry_type: str = "free"

class MilestoneCreate(BaseModel):
    title: str
    target_date: Optional[str] = None

class DependencyCreate(BaseModel):
    depends_on_goal_id: int

class PlanCreate(BaseModel):
    main_goal: str = ""
    tasks: list[dict] = []

class MasteryCheckSubmit(BaseModel):
    response: str

# ---------------------------------------------------------------------------
# Pure math helpers (no LLM — used for reliable trend numbers)
# ---------------------------------------------------------------------------

def linear_slope(values: list) -> float:
    clean = [float(v) for v in values if v is not None]
    n = len(clean)
    if n < 2:
        return 0.0
    x_mean = (n - 1) / 2
    y_mean = sum(clean) / n
    num = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(clean))
    den = sum((i - x_mean) ** 2 for i in range(n))
    return num / den if den else 0.0

def describe_trend(slope: float, threshold: float = 0.05) -> str:
    if slope > threshold:  return "trending up"
    if slope < -threshold: return "trending down"
    return "flat"

def safe_int(value, default=0):
    try:    return int(value)
    except: return default

def safe_rating(value, default=3):
    try:    return int(value)
    except: return default

def calc_streak(unique_dates_desc: list[str], today: str) -> int:
    if not unique_dates_desc:
        return 0
    streak = 0
    expected = datetime.strptime(today, "%Y-%m-%d")
    for date_str in unique_dates_desc:
        date = datetime.strptime(date_str, "%Y-%m-%d")
        if date == expected or date == expected - timedelta(days=1):
            streak += 1
            expected = date - timedelta(days=1)
        else:
            break
    return streak

def avg(lst, key=None):
    items = [e[key] for e in lst] if key else lst
    return round(sum(items) / len(items), 1) if items else None

# ---------------------------------------------------------------------------
# XP Ledger — single source of truth for XP
# ---------------------------------------------------------------------------

def ledger_add(source_type: str, source_id: str, category: str, xp: int):
    """Append an XP event. Idempotent via source_type+source_id upsert."""
    supabase.table("xp_ledger").upsert(
        {
            "source_type": source_type,
            "source_id":   str(source_id),
            "category":    category,
            "xp":          xp,
            "earned_at":   datetime.now(timezone.utc).isoformat(),
        },
        on_conflict="source_type,source_id"
    ).execute()

def get_category_xp(category: str) -> int:
    """Total XP for a category from the ledger."""
    try:
        result = (
            supabase.table("xp_ledger")
            .select("xp")
            .eq("category", category)
            .execute()
        )
        return sum(row["xp"] for row in result.data)
    except Exception:
        # Fallback: count completed tasks × XP_PER_TASK (backward compat)
        return _fallback_category_xp(category)

def _fallback_category_xp(category: str) -> int:
    goals = supabase.table("goals").select("id").eq("category", category).execute()
    if not goals.data:
        return 0
    ids = [g["id"] for g in goals.data]
    tasks = supabase.table("goal_tasks").select("is_completed").in_("goal_id", ids).execute()
    return sum(XP_PER_TASK for t in tasks.data if t["is_completed"])

def get_total_xp() -> int:
    try:
        result = supabase.table("xp_ledger").select("xp").execute()
        return sum(row["xp"] for row in result.data)
    except Exception:
        return 0

def xp_to_level(xp: int) -> dict:
    level = xp // XP_PER_LEVEL + 1
    progress = xp % XP_PER_LEVEL
    return {"level": level, "xp": xp, "xp_in_level": progress, "xp_to_next": XP_PER_LEVEL - progress}

# ---------------------------------------------------------------------------
# Achievement system
# ---------------------------------------------------------------------------

ACHIEVEMENTS = [
    {"key": "first_entry",   "name": "First Step",        "xp": 50,  "check": lambda s: s["total_entries"] >= 1},
    {"key": "streak_7",      "name": "Week Warrior",       "xp": 100, "check": lambda s: s["best_habit_streak"] >= 7},
    {"key": "streak_30",     "name": "Iron Will",          "xp": 300, "check": lambda s: s["best_habit_streak"] >= 30},
    {"key": "entries_10",    "name": "Consistent Voice",   "xp": 75,  "check": lambda s: s["total_entries"] >= 10},
    {"key": "entries_30",    "name": "Dedicated Writer",   "xp": 150, "check": lambda s: s["total_entries"] >= 30},
    {"key": "quests_5",      "name": "Quest Starter",      "xp": 100, "check": lambda s: s["completed_tasks"] >= 5},
    {"key": "quests_20",     "name": "Quest Master",       "xp": 250, "check": lambda s: s["completed_tasks"] >= 20},
    {"key": "mood_up_week",  "name": "Rising Tide",        "xp": 75,  "check": lambda s: s["mood_slope"] > 0.1},
    {"key": "skill_node_1",  "name": "First Unlock",       "xp": 100, "check": lambda s: s["completed_nodes"] >= 1},
    {"key": "skill_node_5",  "name": "Skill Builder",      "xp": 200, "check": lambda s: s["completed_nodes"] >= 5},
    {"key": "level_5",       "name": "Level 5 Reached",    "xp": 200, "check": lambda s: s["level"] >= 5},
    {"key": "level_10",      "name": "Veteran",            "xp": 500, "check": lambda s: s["level"] >= 10},
]

def build_achievement_snapshot() -> dict:
    """Compute current stats for achievement checks."""
    entries  = fetch_all_entries_light()
    streaks  = _compute_streaks_raw()
    tasks    = supabase.table("goal_tasks").select("is_completed").execute().data
    nodes    = supabase.table("skill_progress").select("node_id").execute().data
    total_xp = get_total_xp()
    moods    = [e["mood"] for e in entries]
    return {
        "total_entries":    len(entries),
        "best_habit_streak": max((v["current_streak"] for v in streaks.values()), default=0),
        "completed_tasks":  sum(1 for t in tasks if t["is_completed"]),
        "completed_nodes":  len(nodes),
        "mood_slope":       linear_slope(moods),
        "level":            xp_to_level(total_xp)["level"],
    }

def award_achievements():
    """Check and grant any newly-earned achievements. Idempotent."""
    try:
        existing = {r["name"] for r in supabase.table("achievements").select("name").execute().data}
        snap = build_achievement_snapshot()
        newly_earned = []
        for ach in ACHIEVEMENTS:
            if ach["name"] not in existing and ach["check"](snap):
                supabase.table("achievements").insert({
                    "user_key":  "default",
                    "name":      ach["name"],
                    "xp_bonus":  ach["xp"],
                    "earned_at": datetime.now(timezone.utc).isoformat(),
                }).execute()
                ledger_add("achievement", ach["key"], "Personal Growth", ach["xp"])
                newly_earned.append({"name": ach["name"], "xp": ach["xp"]})
        return newly_earned
    except Exception:
        return []

# ---------------------------------------------------------------------------
# Predictive analytics
# ---------------------------------------------------------------------------

def predictive_analytics() -> dict:
    """
    Returns risk scores and flags for:
    - streak_at_risk: habits logged yesterday but not today
    - goal_failure_risk: goals with <20% progress and >14 days old
    - declining_consistency: journal gaps > 3 days in last 14
    - stagnation: mood flat + goal flat for 7+ entries
    """
    today     = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

    # Streak risk
    habit_result = supabase.table("habits").select("name, completed_at").execute()
    habit_dates: dict[str, list] = defaultdict(list)
    for row in habit_result.data:
        habit_dates[row["name"]].append(row["completed_at"])
    streak_at_risk = [
        n for n, dates in habit_dates.items()
        if yesterday in dates and today not in dates
    ]

    # Goal failure risk
    goal_data = build_goal_summary()
    failure_risk = [
        {"title": g["title"], "category": g["category"], "progress": g["progress"], "days": g["days_since_created"]}
        for g in goal_data
        if g["total_tasks"] > 0 and g["progress"] < 20 and g["days_since_created"] > 14
    ]

    # Declining consistency (gaps in last 14 days)
    start14 = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    recent_entries = (
        supabase.table("journal_entries")
        .select("created_at")
        .gte("created_at", start14)
        .execute()
    ).data
    days_logged = {e["created_at"][:10] for e in recent_entries}
    expected_days = {
        (datetime.now(timezone.utc) - timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range(14)
    }
    missed_days = sorted(expected_days - days_logged, reverse=True)
    consistency_score = round(len(days_logged) / 14 * 100)
    declining_consistency = consistency_score < 50

    # Stagnation: last 7 entries mood + goal both flat
    all_light = fetch_all_entries_light()
    stagnating = False
    if len(all_light) >= 7:
        last7 = all_light[-7:]
        m_slope = linear_slope([e["mood"] for e in last7])
        g_slope = linear_slope([e["goal_progress"] for e in last7])
        stagnating = abs(m_slope) < 0.05 and abs(g_slope) < 0.3

    return {
        "streak_at_risk":        streak_at_risk,
        "goal_failure_risk":     failure_risk,
        "declining_consistency": declining_consistency,
        "consistency_score":     consistency_score,
        "missed_days_count":     len(missed_days),
        "stagnating":            stagnating,
    }

# ---------------------------------------------------------------------------
# Progression paths
# ---------------------------------------------------------------------------

def build_progression_path(category: str) -> dict:
    """
    For a given category, returns:
    - completed nodes
    - currently unlocked (workable) nodes
    - next recommended node
    - locked nodes with what unlocks them
    """
    tree = resolve_tree(category)
    if not tree:
        return {}

    nodes         = tree["nodes"]
    completed     = [n for n in nodes if n["completed"]]
    unlocked_only = [n for n in nodes if n["unlocked"] and not n["completed"]]
    locked        = [n for n in nodes if not n["unlocked"] and not n["completed"]]

    # Recommend: highest-prereq unlocked node (deepest in tree)
    def depth(node):
        return len(node.get("prerequisites", []))
    recommended = sorted(unlocked_only, key=depth, reverse=True)[0] if unlocked_only else None

    # For each locked node, show what's missing
    for n in locked:
        missing_prereqs = [p for p in n["prerequisites"] if p not in {c["id"] for c in completed}]
        xp_gap          = max(0, n["xp_required"] - tree["category_xp"])
        n["unlocked_by"] = {
            "missing_nodes": missing_prereqs,
            "xp_needed":     xp_gap,
        }

    # For each completed/unlocked, show what it leads to
    for n in completed + unlocked_only:
        n["leads_to"] = [ln["id"] for ln in nodes if n["id"] in ln.get("prerequisites", [])]

    return {
        "category":    category,
        "category_xp": tree["category_xp"],
        "level":       xp_to_level(tree["category_xp"]),
        "completed":   completed,
        "in_progress": unlocked_only,
        "locked":      locked,
        "recommended": recommended,
    }

# ---------------------------------------------------------------------------
# Daily Plan endpoints (existed in original app.js calls)
# ---------------------------------------------------------------------------

@app.post("/plans")
def create_plan(plan: PlanCreate):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    supabase.table("daily_plans").upsert(
        {
            "date":      today,
            "main_goal": plan.main_goal,
            "tasks":     _json.dumps(plan.tasks),
        },
        on_conflict="date"
    ).execute()
    return {"status": "saved"}

@app.get("/plans/today")
def get_today_plan():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    result = supabase.table("daily_plans").select("*").eq("date", today).execute()
    if not result.data:
        return {"plan": None}
    row = result.data[0]
    tasks = _json.loads(row["tasks"]) if isinstance(row["tasks"], str) else (row["tasks"] or [])
    return {"plan": {"main_goal": row.get("main_goal", ""), "tasks": tasks}}

@app.put("/plans/today/reflect")
def reflect_on_plan(data: dict):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    tasks = _json.dumps(data.get("tasks", []))
    supabase.table("daily_plans").update(
        {"tasks": tasks, "reflection_note": data.get("reflection_note", "")}
    ).eq("date", today).execute()
    return {"status": "updated"}

# ---------------------------------------------------------------------------
# Entry CRUD
# ---------------------------------------------------------------------------

def generate_embedding(text: str) -> list[float]:
    return embedding_model.encode(text).tolist()

@app.post("/entries")
def create_entry(entry: EntryCreate):
    combined = (
        f"Title: {entry.title}. Content: {entry.content}. "
        f"Mood: {entry.mood}/5. Energy: {entry.energy}/5. "
        f"Focus: {entry.focus}/5. Goal progress: {entry.goal_progress}%."
    )
    data = {
        "title": entry.title, "content": entry.content,
        "mood": entry.mood, "goal_progress": entry.goal_progress,
        "energy": entry.energy, "focus": entry.focus,
        "entry_type": entry.entry_type,
        "embedding": generate_embedding(combined),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "tags": entry.tags,
    }
    result = supabase.table("journal_entries").insert(data).execute()

    # Grant XP for journaling (into Personal Growth)
    entry_id = result.data[0]["id"]
    xp_map = {"morning": 15, "night": 20, "free": 10}
    ledger_add("journal_entry", str(entry_id), "Personal Growth", xp_map.get(entry.entry_type, 10))

    # Check achievements after every entry
    new_achievements = award_achievements()

    return {"status": "created", "entry": result.data[0], "new_achievements": new_achievements}

@app.get("/entries")
def get_entries(tag: Optional[str] = None, keyword: Optional[str] = None,
                start_date: Optional[str] = None, end_date: Optional[str] = None):
    q = supabase.table("journal_entries").select(
        "id, title, content, mood, goal_progress, energy, focus, entry_type, tags, created_at"
    )
    if tag:        q = q.contains("tags", [tag])
    if keyword:    q = q.or_(f"title.ilike.%{keyword}%,content.ilike.%{keyword}%")
    if start_date: q = q.gte("created_at", start_date)
    if end_date:   q = q.lte("created_at", end_date)
    return q.order("created_at", desc=True).execute().data

@app.get("/entries/trends")
def get_trends(days: int = 30):
    start = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    result = (
        supabase.table("journal_entries")
        .select("mood, goal_progress, energy, focus, created_at")
        .gte("created_at", start).order("created_at").execute()
    )
    daily = {}
    for e in result.data:
        date = e["created_at"][:10]
        daily.setdefault(date, {"moods": [], "goals": [], "energies": [], "focuses": []})
        daily[date]["moods"].append(e["mood"])
        daily[date]["goals"].append(e["goal_progress"])
        daily[date]["energies"].append(e.get("energy") or 3)
        daily[date]["focuses"].append(e.get("focus") or 3)
    return [
        {"date": d,
         "avg_mood":   round(sum(v["moods"])    / len(v["moods"]), 1),
         "avg_goal":   round(sum(v["goals"])    / len(v["goals"]), 1),
         "avg_energy": round(sum(v["energies"]) / len(v["energies"]), 1),
         "avg_focus":  round(sum(v["focuses"])  / len(v["focuses"]), 1)}
        for d, v in sorted(daily.items())
    ]

@app.get("/entries/correlations")
def get_correlations():
    result = supabase.table("journal_entries").select("mood, goal_progress, created_at").execute()
    days = {i: {"moods": [], "goals": []} for i in range(7)}
    for e in result.data:
        dow = datetime.fromisoformat(e["created_at"].replace("Z", "+00:00")).weekday()
        days[dow]["moods"].append(e["mood"])
        days[dow]["goals"].append(e["goal_progress"])
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    return [
        {"day": name,
         "avg_mood": round(sum(days[i]["moods"]) / len(days[i]["moods"]), 1) if days[i]["moods"] else 0,
         "avg_goal": round(sum(days[i]["goals"]) / len(days[i]["goals"]), 1) if days[i]["goals"] else 0}
        for i, name in enumerate(day_names)
    ]

@app.get("/entries/{entry_id}")
def get_entry(entry_id: int):
    result = (
        supabase.table("journal_entries")
        .select("id, title, content, mood, goal_progress, tags, created_at")
        .eq("id", entry_id).single().execute()
    )
    if not result.data:
        raise HTTPException(404, "Entry not found")
    return result.data

@app.put("/entries/{entry_id}")
def update_entry(entry_id: int, entry: EntryCreate):
    combined = (
        f"Title: {entry.title}. Content: {entry.content}. "
        f"Mood: {entry.mood}/5. Energy: {entry.energy}/5. "
        f"Focus: {entry.focus}/5. Goal progress: {entry.goal_progress}%."
    )
    data = {
        "title": entry.title, "content": entry.content,
        "mood": entry.mood, "goal_progress": entry.goal_progress,
        "energy": entry.energy, "focus": entry.focus,
        "entry_type": entry.entry_type, "tags": entry.tags,
        "embedding": generate_embedding(combined),
    }
    result = supabase.table("journal_entries").update(data).eq("id", entry_id).execute()
    if not result.data:
        raise HTTPException(404, "Entry not found")
    return {"status": "updated", "entry": result.data[0]}

@app.delete("/entries/{entry_id}")
def delete_entry(entry_id: int):
    result = supabase.table("journal_entries").delete().eq("id", entry_id).execute()
    if not result.data:
        raise HTTPException(404, "Entry not found")
    return {"status": "deleted"}

# ---------------------------------------------------------------------------
# Habits
# ---------------------------------------------------------------------------

def _compute_streaks_raw() -> dict:
    result = supabase.table("habits").select("name, completed_at").order("completed_at", desc=True).execute()
    habit_dates: dict[str, list] = defaultdict(list)
    for row in result.data:
        habit_dates[row["name"]].append(row["completed_at"])
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return {
        name: {
            "current_streak": calc_streak(sorted(set(dates), reverse=True), today),
            "total_logs": len(dates),
        }
        for name, dates in habit_dates.items()
    }

@app.post("/habits")
def log_habit(habit: HabitLog):
    data = {
        "name": habit.name,
        "completed_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    result = supabase.table("habits").insert(data).execute()
    # Grant XP for logging a habit
    ledger_add("habit", f"{habit.name}:{data['completed_at']}", "Personal Growth", 10)
    new_achievements = award_achievements()
    return {"status": "logged", "habit": result.data[0], "new_achievements": new_achievements}

@app.get("/habits/streaks")
def get_streaks():
    return _compute_streaks_raw()

# ---------------------------------------------------------------------------
# Goals + Milestones + Dependencies
# ---------------------------------------------------------------------------

@app.post("/goals")
def create_goal(goal: GoalCreate):
    result = supabase.table("goals").insert({
        "title": goal.title, "category": goal.category,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "is_completed": False,
    }).execute()
    return {"status": "created", "goal": result.data[0]}

@app.get("/goals")
def get_goals():
    return build_goal_summary()

@app.delete("/goals/{goal_id}")
def delete_goal(goal_id: int):
    supabase.table("goal_tasks").delete().eq("goal_id", goal_id).execute()
    supabase.table("goal_milestones").delete().eq("goal_id", goal_id).execute()
    supabase.table("goal_dependencies").delete().eq("goal_id", goal_id).execute()
    supabase.table("goal_dependencies").delete().eq("depends_on_goal_id", goal_id).execute()
    result = supabase.table("goals").delete().eq("id", goal_id).execute()
    if not result.data:
        raise HTTPException(404, "Goal not found")
    return {"status": "deleted"}

# Milestones
@app.post("/goals/{goal_id}/milestones")
def add_milestone(goal_id: int, ms: MilestoneCreate):
    result = supabase.table("goal_milestones").insert({
        "goal_id": goal_id, "title": ms.title,
        "target_date": ms.target_date,
        "is_completed": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }).execute()
    return result.data[0]

@app.put("/milestones/{ms_id}")
def toggle_milestone(ms_id: int):
    row = supabase.table("goal_milestones").select("*").eq("id", ms_id).single().execute()
    updated = supabase.table("goal_milestones").update(
        {"is_completed": not row.data["is_completed"]}
    ).eq("id", ms_id).execute()
    if updated.data[0]["is_completed"]:
        # Completing a milestone gives XP
        goal = supabase.table("goals").select("category").eq("id", row.data["goal_id"]).single().execute()
        cat  = goal.data.get("category", "Personal Growth")
        ledger_add("milestone", str(ms_id), cat, 75)
        award_achievements()
    return updated.data[0]

# Dependencies
@app.post("/goals/{goal_id}/dependencies")
def add_dependency(goal_id: int, dep: DependencyCreate):
    result = supabase.table("goal_dependencies").insert({
        "goal_id": goal_id,
        "depends_on_goal_id": dep.depends_on_goal_id,
    }).execute()
    return result.data[0]

@app.get("/goals/{goal_id}/dependencies")
def get_dependencies(goal_id: int):
    result = supabase.table("goal_dependencies").select("*").eq("goal_id", goal_id).execute()
    return result.data

# Tasks
@app.post("/goals/{goal_id}/tasks")
def create_task(goal_id: int, task: TaskCreate):
    result = supabase.table("goal_tasks").insert({
        "goal_id": goal_id, "title": task.title,
        "is_completed": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }).execute()
    return result.data[0]

@app.get("/goals/{goal_id}/tasks")
def get_tasks(goal_id: int):
    return supabase.table("goal_tasks").select("*").eq("goal_id", goal_id).execute().data

@app.put("/tasks/{task_id}")
def toggle_task(task_id: int):
    task = supabase.table("goal_tasks").select("*").eq("id", task_id).single().execute()
    is_completing = not task.data["is_completed"]
    updated = supabase.table("goal_tasks").update(
        {"is_completed": is_completing}
    ).eq("id", task_id).execute()

    if is_completing:
        # Grant XP to the goal's category
        goal = supabase.table("goals").select("category").eq("id", task.data["goal_id"]).single().execute()
        cat  = goal.data.get("category", "Personal Growth")
        ledger_add("task", str(task_id), cat, XP_PER_TASK)
        new_achievements = award_achievements()
        # Check if any skill node just became unlockable
        newly_unlockable = _check_new_unlocks(cat)
        return {
            **updated.data[0],
            "xp_earned": XP_PER_TASK,
            "category": cat,
            "new_achievements": new_achievements,
            "newly_unlockable": newly_unlockable,
        }
    return updated.data[0]

def _check_new_unlocks(category: str) -> list[str]:
    """Return node names that just became unlockable after an XP change."""
    try:
        tree = resolve_tree(category)
        if not tree:
            return []
        return [n["name"] for n in tree["nodes"] if n["unlocked"] and not n["completed"]]
    except Exception:
        return []

@app.delete("/tasks/{task_id}")
def delete_task(task_id: int):
    result = supabase.table("goal_tasks").delete().eq("id", task_id).execute()
    if not result.data:
        raise HTTPException(404, "Task not found")
    return {"status": "deleted"}

# ---------------------------------------------------------------------------
# Goal summary builder (shared by all callers)
# ---------------------------------------------------------------------------

def build_goal_summary() -> list[dict]:
    goals     = supabase.table("goals").select("*").order("created_at", desc=True).execute()
    task_rows = supabase.table("goal_tasks").select("*").execute()

    tasks_by_goal: dict[int, list] = defaultdict(list)
    for task in task_rows.data:
        tasks_by_goal[task["goal_id"]].append(task)

    # Milestones
    try:
        ms_rows = supabase.table("goal_milestones").select("*").execute().data
    except Exception:
        ms_rows = []
    ms_by_goal: dict[int, list] = defaultdict(list)
    for ms in ms_rows:
        ms_by_goal[ms["goal_id"]].append(ms)

    summary = []
    for goal in goals.data:
        tasks      = tasks_by_goal.get(goal["id"], [])
        completed  = sum(1 for t in tasks if t["is_completed"])
        total      = len(tasks)
        progress   = round(completed / total * 100) if total > 0 else 0
        xp         = get_category_xp(goal["category"])
        level_info = xp_to_level(xp)
        created    = datetime.fromisoformat(goal["created_at"].replace("Z", "+00:00"))
        days_old   = (datetime.now(timezone.utc) - created).days

        milestones = ms_by_goal.get(goal["id"], [])
        ms_done    = sum(1 for m in milestones if m["is_completed"])

        summary.append({
            **goal,
            "tasks":            tasks,
            "completed_tasks":  completed,
            "total_tasks":      total,
            "progress":         progress,
            "xp":               xp,
            "level":            level_info["level"],
            "xp_in_level":      level_info["xp_in_level"],
            "xp_to_next":       level_info["xp_to_next"],
            "days_since_created": days_old,
            "milestones":       milestones,
            "milestones_done":  ms_done,
            "milestones_total": len(milestones),
        })
    return summary

def build_category_health(summary: list[dict]) -> list[dict]:
    by_cat: dict[str, dict] = {}
    for g in summary:
        cat = g.get("category", "Other")
        by_cat.setdefault(cat, {"xp": 0, "completed": 0, "total": 0, "days": []})
        by_cat[cat]["xp"]       += g["xp"]
        by_cat[cat]["completed"] += g["completed_tasks"]
        by_cat[cat]["total"]     += g["total_tasks"]
        by_cat[cat]["days"].append(g["days_since_created"])
    health = []
    for cat, data in by_cat.items():
        rate   = round(data["completed"] / data["total"] * 100) if data["total"] > 0 else 0
        oldest = max(data["days"])
        stale  = oldest > 7 and rate < 50
        health.append({
            "category": cat, "total_xp": data["xp"],
            "completion_rate": rate, "stale": stale,
            "oldest_goal_days": oldest,
        })
    return sorted(health, key=lambda x: x["total_xp"], reverse=True)

@app.get("/goals/summary")
def goals_summary():
    return build_goal_summary()

# ---------------------------------------------------------------------------
# Skill Trees
# ---------------------------------------------------------------------------

SKILL_TREES: dict[str, dict] = {
    "Study": {
        "label": "Computer Science", "icon": "📚", "color": "#6c8ebf",
        "nodes": [
            {"id": "cs_fundamentals", "name": "Programming Fundamentals",
             "xp_required": 0, "prerequisites": [],
             "description": "Variables, loops, functions, and basic problem solving.",
             "mastery_check": {"type": "reflection", "prompt": "Describe the difference between a loop and a function. Give a real example from your own study."}},
            {"id": "cs_python", "name": "Python Basics",
             "xp_required": 100, "prerequisites": ["cs_fundamentals"],
             "description": "Syntax, data types, list comprehensions, modules.",
             "mastery_check": {"type": "challenge", "prompt": "Write (or describe from memory) a Python function that takes a list of numbers and returns only the even ones using a list comprehension."}},
            {"id": "cs_dsa", "name": "Data Structures",
             "xp_required": 200, "prerequisites": ["cs_fundamentals"],
             "description": "Arrays, linked lists, stacks, queues, hashmaps.",
             "mastery_check": {"type": "quiz", "prompt": "Explain when you'd choose a hashmap over an array. Give a concrete use case you've encountered or studied."}},
            {"id": "cs_algorithms", "name": "Algorithms",
             "xp_required": 400, "prerequisites": ["cs_dsa"],
             "description": "Sorting, searching, recursion, dynamic programming.",
             "mastery_check": {"type": "challenge", "prompt": "Explain merge sort in your own words and describe why it's O(n log n). No need to write code — prove you understand it."}},
            {"id": "cs_oop", "name": "Object-Oriented Programming",
             "xp_required": 300, "prerequisites": ["cs_python"],
             "description": "Classes, inheritance, polymorphism, design patterns.",
             "mastery_check": {"type": "reflection", "prompt": "Describe a real project or exercise where you used inheritance or polymorphism. What problem did it solve?"}},
            {"id": "cs_web", "name": "Web Development",
             "xp_required": 350, "prerequisites": ["cs_oop"],
             "description": "APIs, HTTP, frontend basics, backend frameworks.",
             "mastery_check": {"type": "proof", "prompt": "Share a link to a project, GitHub repo, or describe in detail a web app you built. What does it do? What stack?"}},
            {"id": "cs_ai", "name": "AI & Machine Learning",
             "xp_required": 600, "prerequisites": ["cs_algorithms", "cs_oop"],
             "description": "ML fundamentals, neural networks, model training.",
             "mastery_check": {"type": "quiz", "prompt": "Explain overfitting: what causes it, how do you detect it, and two techniques to prevent it."}},
            {"id": "cs_security", "name": "Cybersecurity",
             "xp_required": 500, "prerequisites": ["cs_web", "cs_algorithms"],
             "description": "Threats, encryption, auth, secure coding.",
             "mastery_check": {"type": "challenge", "prompt": "Describe how SQL injection works and show (in pseudocode or plain English) how parameterized queries prevent it."}},
        ],
    },
    "Fitness": {
        "label": "Physical Mastery", "icon": "💪", "color": "#82b366",
        "nodes": [
            {"id": "fit_consistency", "name": "Consistency",
             "xp_required": 0, "prerequisites": [],
             "description": "Exercise at least 3x/week for 4 consecutive weeks.",
             "mastery_check": {"type": "proof", "prompt": "Describe your current weekly exercise schedule. How many consecutive weeks have you maintained it? Be honest."}},
            {"id": "fit_strength", "name": "Strength Foundation",
             "xp_required": 100, "prerequisites": ["fit_consistency"],
             "description": "Master compound lifts: squat, deadlift, press.",
             "mastery_check": {"type": "reflection", "prompt": "What are your current working weights for squat, deadlift, and press? What cues do you focus on for each?"}},
            {"id": "fit_cardio", "name": "Cardio Base",
             "xp_required": 100, "prerequisites": ["fit_consistency"],
             "description": "Run 5km without stopping.",
             "mastery_check": {"type": "proof", "prompt": "Have you run 5km without stopping? Share your approximate time or describe the experience."}},
            {"id": "fit_nutrition", "name": "Nutrition Basics",
             "xp_required": 150, "prerequisites": ["fit_consistency"],
             "description": "Track macros, meal prep, understand caloric balance.",
             "mastery_check": {"type": "quiz", "prompt": "Explain what a caloric deficit is and roughly how many calories are in 1g of protein, fat, and carbs."}},
            {"id": "fit_advanced", "name": "Advanced Training",
             "xp_required": 400, "prerequisites": ["fit_strength", "fit_cardio"],
             "description": "Periodization, progressive overload, recovery.",
             "mastery_check": {"type": "challenge", "prompt": "Design a 4-week progressive overload plan for one compound lift. Show the week-by-week progression."}},
        ],
    },
    "Finance": {
        "label": "Financial Intelligence", "icon": "💰", "color": "#d6a73a",
        "nodes": [
            {"id": "fin_budgeting", "name": "Budgeting",
             "xp_required": 0, "prerequisites": [],
             "description": "Track income and expenses, build a monthly budget.",
             "mastery_check": {"type": "reflection", "prompt": "What does your current monthly budget look like? What are your top 3 expense categories?"}},
            {"id": "fin_emergency", "name": "Emergency Fund",
             "xp_required": 100, "prerequisites": ["fin_budgeting"],
             "description": "Save 3 months of expenses.",
             "mastery_check": {"type": "proof", "prompt": "How many months of expenses do you currently have saved? What's your monthly expense baseline?"}},
            {"id": "fin_debt", "name": "Debt Elimination",
             "xp_required": 150, "prerequisites": ["fin_budgeting"],
             "description": "Avalanche or snowball method to eliminate debt.",
             "mastery_check": {"type": "quiz", "prompt": "Explain the difference between the avalanche and snowball debt repayment methods. Which would you choose and why?"}},
            {"id": "fin_investing", "name": "Investing Basics",
             "xp_required": 300, "prerequisites": ["fin_emergency"],
             "description": "Index funds, ETFs, compound interest, tax-advantaged accounts.",
             "mastery_check": {"type": "challenge", "prompt": "Explain compound interest with a concrete example: what happens to ₱10,000 invested at 8% annually for 10 years?"}},
            {"id": "fin_income", "name": "Income Growth",
             "xp_required": 400, "prerequisites": ["fin_debt", "fin_investing"],
             "description": "Side income, salary negotiation, skill monetization.",
             "mastery_check": {"type": "reflection", "prompt": "What's one concrete step you've taken or plan to take to grow your income this year?"}},
        ],
    },
    "Creativity": {
        "label": "Creative Mastery", "icon": "🎨", "color": "#9c70c4",
        "nodes": [
            {"id": "cr_basics", "name": "Creative Foundations",
             "xp_required": 0, "prerequisites": [],
             "description": "Daily practice habit, overcoming blank-page paralysis.",
             "mastery_check": {"type": "reflection", "prompt": "Describe your current creative practice. How often do you create? What do you make?"}},
            {"id": "cr_craft", "name": "Craft Fundamentals",
             "xp_required": 100, "prerequisites": ["cr_basics"],
             "description": "Core techniques for your chosen medium.",
             "mastery_check": {"type": "proof", "prompt": "Share or describe a piece of work that demonstrates a core technique in your medium. What technique does it show?"}},
            {"id": "cr_voice", "name": "Personal Voice",
             "xp_required": 250, "prerequisites": ["cr_craft"],
             "description": "Develop a distinct style others can recognise.",
             "mastery_check": {"type": "reflection", "prompt": "How would you describe your creative style in 3 words? What influences it most?"}},
            {"id": "cr_project", "name": "Finish a Project",
             "xp_required": 200, "prerequisites": ["cr_craft"],
             "description": "Complete one significant creative work end-to-end.",
             "mastery_check": {"type": "proof", "prompt": "Describe a complete creative project you've finished recently. What was the hardest part of finishing it?"}},
            {"id": "cr_share", "name": "Share Your Work",
             "xp_required": 350, "prerequisites": ["cr_voice", "cr_project"],
             "description": "Publish, perform, or exhibit. Feedback loop matters.",
             "mastery_check": {"type": "proof", "prompt": "Where did you share your work? What was the response? (A link, a description of a performance, or a screenshot description works.)"}},
        ],
    },
    "Personal Growth": {
        "label": "Self Mastery", "icon": "🌱", "color": "#d07040",
        "nodes": [
            {"id": "pg_awareness", "name": "Self Awareness",
             "xp_required": 0, "prerequisites": [],
             "description": "Daily journaling, identify core values and blind spots.",
             "mastery_check": {"type": "reflection", "prompt": "Name 3 of your core values and one blind spot you've identified through journaling. Be specific."}},
            {"id": "pg_habits", "name": "Habit Architecture",
             "xp_required": 100, "prerequisites": ["pg_awareness"],
             "description": "Design habit stacks, track streaks, remove friction.",
             "mastery_check": {"type": "challenge", "prompt": "Describe one habit you've built successfully. What cue triggers it, what's the routine, and what's the reward?"}},
            {"id": "pg_mindset", "name": "Growth Mindset",
             "xp_required": 150, "prerequisites": ["pg_awareness"],
             "description": "Reframe failure, embrace discomfort, learn from feedback.",
             "mastery_check": {"type": "reflection", "prompt": "Describe a recent failure or setback. How did you respond to it? What did you learn?"}},
            {"id": "pg_focus", "name": "Deep Focus",
             "xp_required": 200, "prerequisites": ["pg_habits"],
             "description": "Deep work sessions, distraction elimination, flow state.",
             "mastery_check": {"type": "challenge", "prompt": "Describe your current deep work setup. How long can you focus without distraction? What's your best session length this week?"}},
            {"id": "pg_leadership", "name": "Leadership",
             "xp_required": 500, "prerequisites": ["pg_mindset", "pg_focus"],
             "description": "Influence, communication, accountability to others.",
             "mastery_check": {"type": "reflection", "prompt": "Describe a situation where you led, influenced, or held someone (including yourself) accountable. What was the outcome?"}},
        ],
    },
}

def get_completed_node_ids(category: str) -> set[str]:
    result = (
        supabase.table("skill_progress")
        .select("node_id").eq("category", category).execute()
    )
    return {row["node_id"] for row in result.data}

def resolve_tree(category: str) -> dict:
    tree_def = SKILL_TREES.get(category)
    if not tree_def:
        return {}
    xp           = get_category_xp(category)
    completed_ids = get_completed_node_ids(category)
    resolved     = []
    for node in tree_def["nodes"]:
        prereqs_met = all(p in completed_ids for p in node["prerequisites"])
        xp_met      = xp >= node["xp_required"]
        unlocked    = prereqs_met and xp_met
        completed   = node["id"] in completed_ids
        resolved.append({
            **node,
            "unlocked":    unlocked,
            "completed":   completed,
            "prereqs_met": prereqs_met,
            "xp_met":      xp_met,
            "category_xp": xp,
            "leads_to": [n["id"] for n in tree_def["nodes"] if node["id"] in n["prerequisites"]],
        })
    return {**tree_def, "category": category, "category_xp": xp, "nodes": resolved}

@app.get("/skills")
def get_skills():
    return [resolve_tree(cat) for cat in SKILL_TREES]

@app.get("/skills/{category}")
def get_skill_tree(category: str):
    tree = resolve_tree(category)
    if not tree:
        raise HTTPException(404, "Skill tree not found")
    return tree

@app.get("/progression/{category}")
def get_progression(category: str):
    path = build_progression_path(category)
    if not path:
        raise HTTPException(404, "Category not found")
    return path

# Mastery check endpoints
@app.get("/skills/{node_id}/mastery-check")
def get_mastery_check(node_id: str, category: str):
    """Return the mastery check prompt for a node."""
    tree = resolve_tree(category)
    if not tree:
        raise HTTPException(404, "Tree not found")
    node = next((n for n in tree["nodes"] if n["id"] == node_id), None)
    if not node:
        raise HTTPException(404, "Node not found")
    if not node["unlocked"]:
        raise HTTPException(403, "Node not yet unlocked")
    # Check if already passed
    try:
        existing = (
            supabase.table("skill_mastery_checks")
            .select("*").eq("node_id", node_id).eq("passed", True).execute()
        )
        if existing.data:
            return {**node["mastery_check"], "already_passed": True}
    except Exception:
        pass
    return {**node["mastery_check"], "already_passed": False}

@app.post("/skills/{node_id}/mastery-check")
def submit_mastery_check(node_id: str, category: str, submission: MasteryCheckSubmit):
    """AI evaluates the user's mastery check response."""
    tree = resolve_tree(category)
    if not tree:
        raise HTTPException(404, "Tree not found")
    node = next((n for n in tree["nodes"] if n["id"] == node_id), None)
    if not node:
        raise HTTPException(404, "Node not found")
    if not node["unlocked"]:
        raise HTTPException(403, "Node not yet unlocked")

    check = node.get("mastery_check", {})
    prompt_text = check.get("prompt", "")
    check_type  = check.get("type", "reflection")

    eval_prompt = f"""You are evaluating a learner's mastery check for a skill node.

Skill: {node["name"]}
Check type: {check_type}
Question/Challenge: {prompt_text}

Learner's response:
{submission.response}

Evaluate whether this response demonstrates genuine understanding and mastery.

Rules:
- For 'reflection': They must show real self-awareness and specificity. Vague or generic answers fail.
- For 'quiz': They must get the core concept right. Minor errors are OK if understanding is clear.
- For 'challenge': They must demonstrate they can apply the skill. Conceptual explanation is fine, code not required.
- For 'proof': They must describe real evidence of doing the thing, not just saying they plan to.
- Be reasonably strict. "I know about it" is not mastery. "Here's exactly how I've applied it" is.

Respond ONLY in this JSON format:
{{
  "passed": true or false,
  "score": a number 0-100,
  "feedback": "2-3 sentences of honest, constructive feedback",
  "what_was_good": "one specific thing they did well (or null if failed badly)",
  "what_to_improve": "one specific thing they should do before retrying (or null if passed)"
}}"""

    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": eval_prompt}],
        temperature=0.3,
        max_tokens=300,
    )
    raw = response.choices[0].message.content.strip()
    try:
        result = _json.loads(raw)
    except _json.JSONDecodeError:
        raise HTTPException(500, "Evaluation failed")

    # Store the check result
    try:
        supabase.table("skill_mastery_checks").insert({
            "node_id":    node_id,
            "category":   category,
            "check_type": check_type,
            "prompt":     prompt_text,
            "response":   submission.response,
            "passed":     result["passed"],
            "score":      result.get("score", 0),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception:
        pass

    return result

@app.post("/skills/{node_id}/complete")
def complete_skill_node(node_id: str, category: str):
    """Complete a skill node. Requires mastery check to have been passed."""
    tree = resolve_tree(category)
    if not tree:
        raise HTTPException(404, "Tree not found")
    node = next((n for n in tree["nodes"] if n["id"] == node_id), None)
    if not node:
        raise HTTPException(404, "Node not found")
    if not node["unlocked"]:
        raise HTTPException(403, "Node not yet unlocked")

    # Require mastery check to be passed
    try:
        check_result = (
            supabase.table("skill_mastery_checks")
            .select("passed").eq("node_id", node_id).eq("passed", True).execute()
        )
        if not check_result.data:
            raise HTTPException(403, "Mastery check not yet passed. Complete the check first.")
    except HTTPException:
        raise
    except Exception:
        pass  # If table doesn't exist yet, allow completion (backward compat)

    supabase.table("skill_progress").upsert({
        "node_id":      node_id,
        "category":     category,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }).execute()

    # Grant XP bonus for completing a skill node
    xp_bonus = node["xp_required"] // 2 + 50  # scales with difficulty
    ledger_add("skill_node", node_id, category, xp_bonus)
    new_achievements = award_achievements()

    # Build what this unlocks next
    updated_tree = resolve_tree(category)
    newly_unlocked = [
        n["name"] for n in updated_tree["nodes"]
        if n["unlocked"] and not n["completed"] and n["id"] != node_id
    ]

    return {
        "status":          "completed",
        "node_id":         node_id,
        "xp_earned":       xp_bonus,
        "new_achievements": new_achievements,
        "newly_unlocked":  newly_unlocked,
    }

@app.delete("/skills/{node_id}/complete")
def uncomplete_skill_node(node_id: str, category: str):
    supabase.table("skill_progress").delete().eq("node_id", node_id).execute()
    return {"status": "removed", "node_id": node_id}

# ---------------------------------------------------------------------------
# Achievements
# ---------------------------------------------------------------------------

@app.get("/achievements")
def get_achievements():
    try:
        earned = supabase.table("achievements").select("*").order("earned_at", desc=True).execute().data
    except Exception:
        earned = []
    total_xp = get_total_xp()
    return {
        "earned":    earned,
        "total_xp":  total_xp,
        "level_info": xp_to_level(total_xp),
        "all_achievements": [{"name": a["name"], "xp": a["xp"]} for a in ACHIEVEMENTS],
    }

# ---------------------------------------------------------------------------
# Predictive analytics endpoint
# ---------------------------------------------------------------------------

@app.get("/analytics/predictive")
def get_predictive():
    return predictive_analytics()

# ---------------------------------------------------------------------------
# Proactive AI coaching
# ---------------------------------------------------------------------------

@app.get("/coaching/proactive")
def proactive_coaching():
    """
    Detects stagnation, missed goals, streak risks, declining consistency,
    and returns a brief AI-generated proactive nudge + structured alerts.
    """
    analytics = predictive_analytics()
    all_light  = fetch_all_entries_light()
    goal_data  = build_goal_summary()

    # Only call the LLM if something needs attention
    alerts = []
    if analytics["streak_at_risk"]:
        alerts.append(f"Habit streak at risk: {', '.join(analytics['streak_at_risk'])}")
    if analytics["goal_failure_risk"]:
        names = ", ".join(g["title"] for g in analytics["goal_failure_risk"][:2])
        alerts.append(f"Goals at risk of failure: {names}")
    if analytics["declining_consistency"]:
        alerts.append(f"Journaling consistency dropped to {analytics['consistency_score']}%")
    if analytics["stagnating"]:
        alerts.append("Mood and goal progress both flat for 7+ entries")

    # Stalled goal categories
    cat_health   = build_category_health(goal_data)
    stale_cats   = [c["category"] for c in cat_health if c["stale"]]
    if stale_cats:
        alerts.append(f"Stalled categories: {', '.join(stale_cats)}")

    if not alerts:
        return {"alerts": [], "nudge": None, "needs_attention": False}

    # Recent mood context
    recent7 = all_light[-7:]
    avg_mood_7 = avg([e["mood"] for e in recent7]) if recent7 else None

    prompt = f"""You are LiAInne, a personal coach. 

Alerts detected for this user:
{chr(10).join(f'- {a}' for a in alerts)}

Recent average mood (last 7 entries): {avg_mood_7}/5

Write ONE short, warm, direct coaching message (max 60 words) that:
- Acknowledges the most urgent issue
- Gives one concrete action to take today
- Sounds like a caring friend, not a dashboard

Do not list all the alerts. Pick the most important one and speak to it."""

    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.8,
        max_tokens=120,
    )
    nudge = response.choices[0].message.content.strip()

    return {
        "needs_attention": True,
        "alerts":          alerts,
        "nudge":           nudge,
        "analytics":       analytics,
    }

# ---------------------------------------------------------------------------
# Daily Quest (auto-generates quests from journal + goals)
# ---------------------------------------------------------------------------

@app.post("/daily-quest")
def daily_quest():
    summary = build_goal_summary()
    pending_lines = []
    for g in summary:
        pending = [t["title"] for t in g["tasks"] if not t["is_completed"]]
        if pending:
            pending_lines.append(
                f'Goal "{g["title"]}" [{g["category"]}] — pending: {", ".join(pending[:3])}'
            )
    if not pending_lines:
        return {"task": None, "message": "All quests complete! Add new ones to keep going."}

    recent = fetch_all_entries_light()[-7:]
    avg_mood = round(sum(e["mood"] for e in recent) / len(recent), 1) if recent else None
    mood_note = f"Recent average mood: {avg_mood}/5." if avg_mood else ""

    # Also include predictive context
    analytics = predictive_analytics()
    risk_note = ""
    if analytics["streak_at_risk"]:
        risk_note = f"URGENT: Habit streak at risk for {', '.join(analytics['streak_at_risk'])}."
    if analytics["stagnating"]:
        risk_note += " User seems stagnant — recommend something that breaks the pattern."

    prompt = f"""You are a quest generator for a personal journal RPG.

Active goals and pending quests:
{chr(10).join(pending_lines)}

{mood_note}
{risk_note}

Pick the single most impactful task the user should do TODAY.
Reply in this exact JSON format (no markdown, no extra text):
{{
  "task": "exact task name from the list",
  "goal": "goal title",
  "category": "category",
  "difficulty": "Easy|Medium|Hard",
  "time": estimated minutes as a number,
  "why": "one sentence reason why this task matters most today",
  "xp": a number between 40 and 150
}}"""

    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7, max_tokens=300,
    )
    raw = response.choices[0].message.content.strip()
    try:
        return _json.loads(raw)
    except _json.JSONDecodeError:
        raise HTTPException(500, "Quest generation failed")

# ---------------------------------------------------------------------------
# Journal → Quest auto-generation
# ---------------------------------------------------------------------------

@app.post("/journal/generate-quests")
def journal_generate_quests(entry_data: dict):
    """
    Given a journal entry (content + mood + entry_type), use AI to
    suggest 1-3 concrete quests derived from the entry.
    These get returned to the frontend for one-click creation.
    """
    content    = entry_data.get("content", "")
    mood       = entry_data.get("mood", 3)
    entry_type = entry_data.get("entry_type", "free")

    goal_data  = build_goal_summary()
    categories = list({g["category"] for g in goal_data}) if goal_data else list(SKILL_TREES.keys())

    prompt = f"""You are a quest extractor for a personal journal RPG.

The user wrote this {entry_type} journal entry (mood: {mood}/5):
"{content[:500]}"

Their active goal categories: {', '.join(categories)}

Extract 1-3 concrete, actionable quests from what they wrote.
Focus on:
- Things they said they wanted to do
- Goals they mentioned struggling with
- Habits they want to build or missed
- Skills they want to learn

Reply ONLY in this JSON format:
[
  {{
    "title": "specific action (< 10 words)",
    "category": "one of: {', '.join(categories)}",
    "reason": "one sentence — what in the entry inspired this",
    "difficulty": "Easy|Medium|Hard",
    "time_minutes": a number 10-60
  }}
]

Return an empty array [] if no clear quests emerge. Max 3 items."""

    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.6, max_tokens=400,
    )
    raw = response.choices[0].message.content.strip()
    try:
        quests = _json.loads(raw)
        return {"quests": quests if isinstance(quests, list) else []}
    except _json.JSONDecodeError:
        return {"quests": []}

# ---------------------------------------------------------------------------
# Action Engine
# ---------------------------------------------------------------------------

def detect_triggers(mood: int, content: str) -> dict:
    reasons, context_parts = [], []
    all_entries = fetch_all_entries_light()
    if len(all_entries) >= 2:
        prev_mood = all_entries[-2]["mood"]
        drop = prev_mood - mood
        if drop >= 2:
            reasons.append(f"mood dropped {drop} points (from {prev_mood} to {mood})")
            context_parts.append(f"Mood drop: {prev_mood} → {mood}/5")
    goal_data   = build_goal_summary()
    cat_health  = build_category_health(goal_data)
    stale_cats  = [c for c in cat_health if c["stale"]]
    if stale_cats:
        worst = stale_cats[0]
        reasons.append(f"{worst['category']} goals inactive for {worst['oldest_goal_days']}+ days")
        context_parts.append(f"Stale category: {worst['category']} ({worst['completion_rate']}% done)")
    habit_result = supabase.table("habits").select("name, completed_at").execute()
    today     = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    habit_dates: dict[str, list] = defaultdict(list)
    for row in habit_result.data:
        habit_dates[row["name"]].append(row["completed_at"])
    at_risk = [
        n for n, dates in habit_dates.items()
        if yesterday in dates and today not in dates
    ]
    if at_risk:
        reasons.append(f"streak at risk: {', '.join(at_risk)}")
        context_parts.append(f"Habits not done today (streak at risk): {', '.join(at_risk)}")
    zero_goals = [
        g for g in goal_data
        if g["total_tasks"] > 0 and g["progress"] == 0 and g["days_since_created"] >= 7
    ]
    if zero_goals:
        names = ", ".join(g["title"] for g in zero_goals[:2])
        reasons.append(f"goals with 0% progress after 7+ days: {names}")
        context_parts.append(f"Zero-progress goals (7+ days old): {names}")
    return {
        "triggered": bool(reasons), "reasons": reasons,
        "context": "\n".join(context_parts),
        "goal_data": goal_data, "stale_cats": stale_cats,
        "at_risk_habits": at_risk, "zero_goals": zero_goals,
    }

@app.post("/action-engine")
def action_engine(req: ActionEngineRequest):
    triggers = detect_triggers(req.mood, req.content)
    if not triggers["triggered"]:
        return {"triggered": False, "action": None}
    goal_data = triggers["goal_data"]
    pending_block = "\n".join(
        f'Goal "{g["title"]}" [{g["category"]}] — pending: {", ".join(t["title"] for t in g["tasks"] if not t["is_completed"])[:2]}'
        for g in goal_data if any(not t["is_completed"] for t in g["tasks"])
    ) or "No active quests yet."
    prompt = f"""You are a behavior coach inside a personal journal app.

Problems detected:
{triggers["context"]}

Entry content: "{req.content[:300]}"

Active goals:
{pending_block}

Prescribe ONE specific action (5-30 min). Be specific. Match it to an existing quest if possible.

Reply ONLY in this JSON:
{{
  "action": "specific task title",
  "reason": "one sentence",
  "trigger_type": "mood_drop|stale_goal|streak_risk|zero_progress",
  "category": "goal category or Wellness",
  "xp": 20-80,
  "duration_minutes": 5-30,
  "is_existing_quest": true or false,
  "goal_title": "goal title or null"
}}"""
    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.6, max_tokens=300,
    )
    try:
        action = _json.loads(response.choices[0].message.content.strip())
    except _json.JSONDecodeError:
        return {"triggered": True, "action": None, "error": "parse_failed"}
    created_quest = None
    if not action.get("is_existing_quest") and action.get("goal_title"):
        match = next(
            (g for g in goal_data if g["title"].lower() == action["goal_title"].lower()), None
        )
        if match:
            result = supabase.table("goal_tasks").insert({
                "goal_id": match["id"], "title": action["action"],
                "is_completed": False,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }).execute()
            if result.data:
                created_quest = result.data[0]
    return {
        "triggered": True, "reasons": triggers["reasons"],
        "action": action, "quest_created": created_quest is not None, "quest": created_quest,
    }

# ---------------------------------------------------------------------------
# Context builders for chat + AI insight
# ---------------------------------------------------------------------------

def fetch_all_entries_light():
    result = (
        supabase.table("journal_entries")
        .select("id, mood, goal_progress, energy, focus, entry_type, created_at")
        .order("created_at").execute()
    )
    return [
        {
            "id": e["id"],
            "mood": safe_rating(e.get("mood")),
            "goal_progress": safe_int(e.get("goal_progress")),
            "energy": safe_rating(e.get("energy")),
            "focus": safe_rating(e.get("focus")),
            "entry_type": e.get("entry_type") or "free",
            "created_at": e["created_at"],
        }
        for e in result.data
    ]

def build_recent_text_block(today_iso: str) -> str:
    start = (datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)).isoformat()
    result = (
        supabase.table("journal_entries")
        .select("id, title, content, mood, goal_progress, energy, focus, entry_type, tags, created_at")
        .gte("created_at", start).order("created_at", desc=True).execute()
    )
    if not result.data:
        return "No entries in the last 14 days."
    parts = []
    for e in result.data:
        tags = f" [tags: {', '.join(e['tags'])}]" if e.get("tags") else ""
        parts.append(
            f"[{e['created_at'][:10]}] [{e.get('entry_type','free')}] "
            f"(Mood: {e['mood']}/5, Energy: {e.get('energy',3)}/5, "
            f"Focus: {e.get('focus',3)}/5, Goal: {e['goal_progress']}%){tags} "
            f"{e['title']}: {e['content']}"
        )
    return "\n\n".join(parts)

def build_weekly_summary_block(all_light_entries: list[dict]) -> str:
    cutoff = datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)
    older = [
        e for e in all_light_entries
        if datetime.fromisoformat(e["created_at"].replace("Z", "+00:00")) < cutoff
    ]
    if not older:
        return "No older entries yet."
    weekly = defaultdict(lambda: {"moods": [], "goals": [], "count": 0})
    for e in older:
        dt = datetime.fromisoformat(e["created_at"].replace("Z", "+00:00"))
        year, week, _ = dt.isocalendar()
        key = f"{year}-W{week:02d}"
        weekly[key]["moods"].append(e["mood"])
        weekly[key]["goals"].append(e["goal_progress"])
        weekly[key]["count"] += 1
    rows = [
        f"{k}: avg mood {round(sum(v['moods'])/len(v['moods']),1)}/5, "
        f"avg goal {round(sum(v['goals'])/len(v['goals']),1)}%, {v['count']} entries"
        for k in sorted(weekly.keys())
    ]
    if len(rows) > MAX_WEEKLY_ROWS:
        h, t = rows[:MAX_WEEKLY_ROWS//2], rows[-(MAX_WEEKLY_ROWS//2):]
        rows = h + [f"... ({len(rows)-len(h)-len(t)} weeks omitted) ..."] + t
    return "\n".join(rows)

def build_trend_stats_block(all_light_entries: list[dict]) -> str:
    if not all_light_entries:
        return "No data yet."
    moods  = [e["mood"] for e in all_light_entries]
    goals  = [e["goal_progress"] for e in all_light_entries]
    r7, p7 = all_light_entries[-7:], all_light_entries[-14:-7] if len(all_light_entries) >= 14 else []
    lines  = [
        f"Overall mood trend: {describe_trend(linear_slope(moods))} over {len(moods)} entries.",
        f"Overall goal trend: {describe_trend(linear_slope(goals), 0.5)} over {len(goals)} entries.",
    ]
    if p7:
        lines.append(
            f"Last 7 avg: mood {avg([e['mood'] for e in r7])}/5, goal {avg([e['goal_progress'] for e in r7])}%. "
            f"Prev 7 avg: mood {avg([e['mood'] for e in p7])}/5, goal {avg([e['goal_progress'] for e in p7])}%."
        )
    return "\n".join(lines)

def build_habit_block() -> str:
    result = supabase.table("habits").select("name, completed_at").order("completed_at", desc=True).execute()
    habit_dates: dict[str, list] = defaultdict(list)
    for row in result.data:
        habit_dates[row["name"]].append(row["completed_at"])
    if not habit_dates:
        return "No habits tracked yet."
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return "\n".join(
        f"- {name}: {calc_streak(sorted(set(dates), reverse=True), today)}-day streak, "
        f"{len(dates)} total, last done {sorted(set(dates), reverse=True)[0] if dates else 'never'}"
        for name, dates in habit_dates.items()
    )

def build_semantic_matches_block(message: str, exclude_ids: set[int]) -> str:
    query_emb = generate_embedding(message)
    matches   = supabase.rpc("match_entries", {
        "query_embedding": query_emb, "match_threshold": 0.3, "match_count": 5
    }).execute()
    relevant = [e for e in matches.data if e["id"] not in exclude_ids]
    if not relevant:
        return ""
    return "\n\n".join(
        f"[{e['created_at'][:10]}] (Mood: {e['mood']}/5, Goal: {e['goal_progress']}%) "
        f"{e['title']}: {e['content']}"
        for e in relevant
    )

def build_coach_context(message: str) -> str:
    today_iso  = datetime.now(timezone.utc).isoformat()
    all_light  = fetch_all_entries_light()
    cutoff_dt  = datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)
    recent_ids = {
        e["id"] for e in all_light
        if datetime.fromisoformat(e["created_at"].replace("Z", "+00:00")) >= cutoff_dt
    }

    # Include predictive context so coach can mention risks
    analytics  = predictive_analytics()
    risk_lines = []
    if analytics["streak_at_risk"]:
        risk_lines.append(f"Habit streaks at risk today: {', '.join(analytics['streak_at_risk'])}")
    if analytics["goal_failure_risk"]:
        risk_lines.append(f"Goals at failure risk: {', '.join(g['title'] for g in analytics['goal_failure_risk'][:2])}")
    if analytics["stagnating"]:
        risk_lines.append("User appears to be stagnating (mood + goal both flat for 7 entries)")

    sections = [
        f"TREND STATISTICS:\n{build_trend_stats_block(all_light)}",
        f"DAY-OF-WEEK PATTERNS:\n" + "\n".join(
            f"{c['day']}: avg mood {c['avg_mood']}/5" for c in get_correlations() if c["avg_mood"] > 0
        ),
        f"HABIT TRACKER:\n{build_habit_block()}",
        f"RISK ALERTS:\n" + ("\n".join(risk_lines) if risk_lines else "No active risks."),
        f"RECENT ENTRIES (last {RECENT_DAYS} days):\n{build_recent_text_block(today_iso)}",
        f"OLDER HISTORY (weekly averages):\n{build_weekly_summary_block(all_light)}",
    ]
    semantic = build_semantic_matches_block(message, recent_ids)
    if semantic:
        sections.append(f"RELEVANT OLDER ENTRIES:\n{semantic}")
    return "\n\n---\n\n".join(sections)

# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_TEMPLATE = (
    "Your name is LiAInne. You are a warm but honest personal coach. "
    "You are not a therapist, doctor, or crisis counselor. "
    "You have access to the user's full journal context including trend stats, "
    "habit streaks, goal progress, risk alerts, and past entries. "
    "Use this privately — do not read it back like a report.\n\n"
    "Before answering, silently decide: (1) What is the real problem? "
    "(2) What pattern or detail from their journal is most relevant? "
    "(3) What is one practical next step they can take today?\n\n"
    "Your response should include: one honest observation, one direct piece of advice, "
    "one small action. Keep it to 2-4 sentences unless they ask for more. "
    "Sound like a thoughtful friend who pays attention — warm, direct, concise. "
    "Never use bullet points unless they ask. "
    "If risk alerts are present, weave the most urgent one into your response naturally.\n\n"
    "Safety: If the user mentions self-harm, suicide, or immediate danger, "
    "respond with care and urgency, and encourage them to contact local emergency services.\n\n"
    "{context}"
)

@app.post("/chat")
def chat(msg: ChatMessage):
    context = build_coach_context(msg.message)
    system  = SYSTEM_PROMPT_TEMPLATE.format(context=context)
    history = [
        {"role": t.role, "content": t.content}
        for t in msg.history[-12:]
        if t.role in ("user", "assistant") and t.content.strip()
    ]
    messages = (
        [{"role": "system", "content": system}]
        + history
        + [{"role": "user", "content": msg.message}]
    )
    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages, temperature=0.8, max_tokens=1024,
    )
    return {"response": response.choices[0].message.content}

# ---------------------------------------------------------------------------
# Insights
# ---------------------------------------------------------------------------

@app.get("/insights")
def get_insights():
    all_light = fetch_all_entries_light()
    if len(all_light) < 3:
        return {"insights": [{"type": "info", "title": "Getting Started",
            "message": "Keep journaling. More entries needed before patterns emerge.",
            "recommendation": "Aim for at least 7 entries to unlock meaningful insights."}]}
    insights = []
    moods = [e["mood"] for e in all_light]
    goals = [e["goal_progress"] for e in all_light]
    m_slope = linear_slope(moods)
    g_slope = linear_slope(goals)
    if m_slope > 0.05:
        insights.append({"type": "success", "title": "Mood Trend",
            "message": "Your mood has been improving over time.",
            "recommendation": "Review recent entries to identify what's helping."})
    elif m_slope < -0.05:
        insights.append({"type": "warning", "title": "Mood Trend",
            "message": "Your mood has been gradually declining.",
            "recommendation": "Look for recurring stressors in your last few entries."})
    if g_slope > 0.5:
        insights.append({"type": "success", "title": "Goal Progress",
            "message": "Goal progress is trending upward.",
            "recommendation": "Keep the current pace."})
    elif g_slope < -0.5:
        insights.append({"type": "warning", "title": "Goal Progress",
            "message": "Goal progress has slowed.",
            "recommendation": "Break goals into smaller daily actions."})
    correlations = get_correlations()
    valid_days   = [d for d in correlations if d["avg_mood"] > 0]
    if valid_days:
        best = max(valid_days, key=lambda d: d["avg_mood"])
        insights.append({"type": "observation", "title": "Best Day",
            "message": f"{best['day']} is your strongest day (avg mood {best['avg_mood']}/5).",
            "recommendation": f"Schedule important work on {best['day']}."})
    streaks = _compute_streaks_raw()
    if streaks:
        best_h = max(streaks.items(), key=lambda x: x[1]["current_streak"])
        if best_h[1]["current_streak"] >= 3:
            insights.append({"type": "success", "title": "Strong Habit",
                "message": f"'{best_h[0]}' has a {best_h[1]['current_streak']}-day streak.",
                "recommendation": "Protect this habit. It's becoming part of your identity."})
    goal_data   = build_goal_summary()
    cat_health  = build_category_health(goal_data)
    if cat_health:
        best_cat = next((c for c in cat_health if c["total_xp"] > 0), None)
        if best_cat:
            insights.append({"type": "success", "title": "Quest Progress",
                "message": f"Progressing fastest in {best_cat['category']} ({best_cat['completion_rate']}% complete, {best_cat['total_xp']} XP).",
                "recommendation": f"Keep momentum in {best_cat['category']}."})
        for s in [c for c in cat_health if c["stale"]][:2]:
            insights.append({"type": "warning", "title": f"{s['category']} Stalled",
                "message": f"{s['category']} goals have been inactive and are only {s['completion_rate']}% complete.",
                "recommendation": f"Open a {s['category']} quest today."})
    # Predictive insights
    analytics = predictive_analytics()
    if analytics["declining_consistency"]:
        insights.append({"type": "warning", "title": "Consistency Dropping",
            "message": f"You've only journaled {analytics['consistency_score']}% of days in the past 2 weeks.",
            "recommendation": "Even a 2-minute entry keeps the streak alive."})
    if analytics["stagnating"]:
        insights.append({"type": "warning", "title": "Growth Plateau",
            "message": "Mood and goal progress have been flat for 7+ entries.",
            "recommendation": "Try something different today — a new habit, a harder quest, or a conversation."})
    if not insights:
        insights.append({"type": "info", "title": "No Strong Patterns Yet",
            "message": "No significant trends detected yet.",
            "recommendation": "Keep journaling consistently."})
    return {"insights": insights}

# ---------------------------------------------------------------------------
# AI insight card
# ---------------------------------------------------------------------------

def build_ai_insight_context():
    all_light = fetch_all_entries_light()
    if len(all_light) < 3:
        return None
    moods     = [e["mood"] for e in all_light]
    goals     = [e["goal_progress"] for e in all_light]
    corr      = get_correlations()
    valid     = [d for d in corr if d["avg_mood"] > 0]
    best_day  = max(valid, key=lambda d: d["avg_mood"]) if valid else None
    streaks   = _compute_streaks_raw()
    best_h    = max(streaks.items(), key=lambda x: x[1]["current_streak"]) if streaks else (None, {"current_streak": 0})
    analytics = predictive_analytics()
    total_xp  = get_total_xp()
    return {
        "entries":            len(all_light),
        "avg_mood":           round(sum(moods) / len(moods), 1),
        "avg_goal_progress":  round(sum(goals) / len(goals), 1),
        "mood_trend":         describe_trend(linear_slope(moods)),
        "goal_trend":         describe_trend(linear_slope(goals), 0.5),
        "best_day":           best_day["day"] if best_day else None,
        "best_day_mood":      best_day["avg_mood"] if best_day else None,
        "strongest_habit":    best_h[0],
        "habit_streak":       best_h[1]["current_streak"],
        "total_xp":           total_xp,
        "level":              xp_to_level(total_xp)["level"],
        "streak_at_risk":     analytics["streak_at_risk"],
        "stagnating":         analytics["stagnating"],
    }

@app.get("/ai-insight")
def ai_insight():
    stats = build_ai_insight_context()
    if not stats:
        return {"insight": "Keep journaling. I need a little more data before I can spot meaningful patterns."}
    prompt = f"""You are LiAInne reviewing a user's journal analytics.

Stats: {stats}

Write:
1. One observation (what you notice)
2. One recommendation (what to do about it)

Rules: Max 80 words. Personal and thoughtful. No statistics listing. No slopes. 
If there's a risk (streak_at_risk or stagnating=True), address it first.
If level >= 5, acknowledge their progress warmly."""

    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "system", "content": prompt}],
        temperature=0.8, max_tokens=150,
    )
    return {"insight": response.choices[0].message.content}

# ---------------------------------------------------------------------------
# Monthly review
# ---------------------------------------------------------------------------

def get_current_month_entries():
    now   = datetime.now(timezone.utc)
    start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    return (
        supabase.table("journal_entries")
        .select("title, content, mood, goal_progress, created_at")
        .gte("created_at", start.isoformat()).order("created_at").execute()
    ).data

@app.get("/monthly-review")
def monthly_review():
    entries = get_current_month_entries()
    if not entries:
        return {"review": "Not enough journal entries this month yet."}
    moods     = [e["mood"] for e in entries]
    goals     = [e["goal_progress"] for e in entries]
    corr      = get_correlations()
    valid     = [d for d in corr if d["avg_mood"] > 0]
    best_day  = max(valid, key=lambda d: d["avg_mood"])["day"] if valid else None
    streaks   = _compute_streaks_raw()
    best_h    = max(streaks.items(), key=lambda x: x[1]["current_streak"])[0] if streaks else None
    goal_data = build_goal_summary()
    cat_health = build_category_health(goal_data)
    total_xp   = sum(g["xp"] for g in goal_data)
    completed_q = sum(g["completed_tasks"] for g in goal_data)
    total_q     = sum(g["total_tasks"] for g in goal_data)
    best_cat    = cat_health[0]["category"] if cat_health else None
    stale_cats  = [c["category"] for c in cat_health if c["stale"]]
    achievements = []
    try:
        achievements = [r["name"] for r in supabase.table("achievements").select("name, earned_at")
            .gte("earned_at", datetime(datetime.now().year, datetime.now().month, 1, tzinfo=timezone.utc).isoformat())
            .execute().data]
    except Exception:
        pass
    context = {
        "entry_count": len(entries),
        "avg_mood": round(sum(moods)/len(moods), 1),
        "avg_goal": round(sum(goals)/len(goals), 1),
        "mood_trend": describe_trend(linear_slope(moods)),
        "goal_trend": describe_trend(linear_slope(goals), 0.5),
        "best_day": best_day, "strongest_habit": best_h,
        "completed_quests": completed_q, "total_quests": total_q,
        "total_xp": total_xp, "best_category": best_cat,
        "stalled_categories": stale_cats,
        "achievements_this_month": achievements,
        "recent_entries": [f"{e['title']}: {e['content'][:150]}" for e in entries[-5:]],
    }
    prompt = f"""You are LiAInne. Create a monthly review.

Context: {context}

Write using exactly these sections:
## Wins
## Challenges  
## Patterns
## Focus For Next Month

Rules: Max 300 words. Honest but encouraging. Mention achievements and stalled goals by name.
Give actionable focus areas. Natural language, not statistics lists."""

    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "system", "content": prompt}],
        temperature=0.7, max_tokens=500,
    )
    return {"review": response.choices[0].message.content}

# ---------------------------------------------------------------------------
# Serve static files
# ---------------------------------------------------------------------------
app.mount("/", StaticFiles(directory="static", html=True), name="static")