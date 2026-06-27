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
    category: str = "Productivity"
    difficulty: str = "Normal"   # Easy | Normal | Hard | Elite
    linked_skill: Optional[str] = None  # category name of a skill tree

class RecoveryTokenUse(BaseModel):
    name: str
    date: str  # YYYY-MM-DD

class GoalCreate(BaseModel):
    title: str
    category: str

class TaskCreate(BaseModel):
    title: str

class ActionEngineRequest(BaseModel):
    mood: int
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


class QuestCreate(BaseModel):
    title: str
    description: str = ""
    difficulty: str = "Normal"
    milestone_id: Optional[int] = None

# ---------------------------------------------------------------------------
# Skill-node tag helpers  (no schema migration needed)
# ---------------------------------------------------------------------------

SKILL_TAG_PREFIX = "skill_node:"

def tag_for_node(node_id: str) -> str:
    return f"{SKILL_TAG_PREFIX}{node_id}"

def node_id_from_tags(tags: list):
    for t in (tags or []):
        if isinstance(t, str) and t.startswith(SKILL_TAG_PREFIX):
            return t[len(SKILL_TAG_PREFIX):]
    return None

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

    # Stagnation: last 7 entries mood + energy both flat
    all_light = fetch_all_entries_light()
    stagnating = False
    if len(all_light) >= 7:
        last7 = all_light[-7:]
        m_slope = linear_slope([e["mood"]   for e in last7])
        e_slope = linear_slope([e["energy"] for e in last7])
        stagnating = abs(m_slope) < 0.05 and abs(e_slope) < 0.05

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

@app.get("/entries/today-status")
def today_entry_status():
    """Return which entry types have already been written today."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    result = (
        supabase.table("journal_entries")
        .select("entry_type")
        .gte("created_at", today + "T00:00:00+00:00")
        .execute()
    )
    done = {row["entry_type"] for row in result.data}
    return {"done": list(done), "morning": "morning" in done, "night": "night" in done, "free": "free" in done}

@app.post("/entries")
def create_entry(entry: EntryCreate):
    # Enforce one entry per type per day (skip check when editing)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    existing = (
        supabase.table("journal_entries")
        .select("id")
        .eq("entry_type", entry.entry_type)
        .gte("created_at", today + "T00:00:00+00:00")
        .execute()
    )
    if existing.data:
        existing_id = existing.data[0]["id"]
        return {"status": "already_exists", "entry_type": entry.entry_type, "existing_id": existing_id,
                "message": f"A {entry.entry_type} entry already exists for today. Edit it instead."}

    combined = (
        f"Title: {entry.title}. Content: {entry.content}. "
        f"Mood: {entry.mood}/5. Energy: {entry.energy}/5. "
        f"Focus: {entry.focus}/5."
    )
    data = {
        "title": entry.title, "content": entry.content,
        "mood": entry.mood,
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
        "id, title, content, mood, energy, focus, entry_type, tags, created_at"
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
        .select("mood, energy, focus, created_at")
        .gte("created_at", start).order("created_at").execute()
    )
    daily = {}
    for e in result.data:
        date = e["created_at"][:10]
        daily.setdefault(date, {"moods": [], "energies": [], "focuses": []})
        daily[date]["moods"].append(e["mood"])
        daily[date]["energies"].append(e.get("energy") or 3)
        daily[date]["focuses"].append(e.get("focus") or 3)
    return [
        {"date": d,
         "avg_mood":   round(sum(v["moods"])    / len(v["moods"]), 1),
         "avg_energy": round(sum(v["energies"]) / len(v["energies"]), 1),
         "avg_focus":  round(sum(v["focuses"])  / len(v["focuses"]), 1)}
        for d, v in sorted(daily.items())
    ]

@app.get("/entries/correlations")
def get_correlations():
    result = supabase.table("journal_entries").select("mood, created_at").execute()
    days = {i: {"moods": []} for i in range(7)}
    for e in result.data:
        dow = datetime.fromisoformat(e["created_at"].replace("Z", "+00:00")).weekday()
        days[dow]["moods"].append(e["mood"])
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    return [
        {"day": name,
         "avg_mood": round(sum(days[i]["moods"]) / len(days[i]["moods"]), 1) if days[i]["moods"] else 0}
        for i, name in enumerate(day_names)
    ]

@app.get("/entries/{entry_id}")
def get_entry(entry_id: int):
    result = (
        supabase.table("journal_entries")
        .select("id, title, content, mood, tags, created_at")
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
        f"Focus: {entry.focus}/5."
    )
    data = {
        "title": entry.title, "content": entry.content,
        "mood": entry.mood,
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
# Habits V2 — Core Gameplay System
# Habits feed Skill Trees, Quests, Domains, AI Coaching, Weekly Bosses
# ---------------------------------------------------------------------------

# ── Pydantic additions ────────────────────────────────────────────────────

class HabitLog(BaseModel):
    name: str
    skill_node_id: str = ""        # e.g. "cs_python"
    skill_tree:    str = ""        # e.g. "Study"
    # Legacy compat fields (ignored if skill_node_id provided)
    category:      str = "Productivity"
    difficulty:    str = "Normal"
    linked_skill:  Optional[str] = None

class HabitCreate(BaseModel):
    name:          str
    skill_node_id: str
    skill_tree:    str

class RecoveryTokenUse(BaseModel):
    name:       str
    date:       str        # YYYY-MM-DD
    token_type: str = "restore"
    # restore | skip | freeze | reroll | bonus_xp | boss_reduce | quest_recover

class EvolutionConfirm(BaseModel):
    confirmed: bool
    new_stage_title: str = ""

# ── Constants ─────────────────────────────────────────────────────────────

MASTERY_LEVELS = [
    (0,   "Beginner"),
    (7,   "Apprentice"),
    (30,  "Journeyman"),
    (90,  "Expert"),
    (180, "Master"),
    (365, "Legend"),
]

EVOLUTION_THRESHOLDS = [7, 21, 60, 120, 200]   # completions to unlock next stage

# Synergy definitions: (sorted frozenset of habit names containing key) → bonus
SYNERGY_RULES = [
    {
        "key":      "mental_clarity",
        "name":     "Mental Clarity",
        "keywords": ["journal", "meditat"],
        "bonus":    "+15% XP for next 24h · Focus insights unlocked",
        "days":     1,
    },
    {
        "key":      "recovery_boost",
        "name":     "Recovery Boost",
        "keywords": ["exercise", "workout", "run", "gym", "sleep"],
        "bonus":    "+20% XP · Streak protection active",
        "days":     1,
    },
    {
        "key":      "learning_momentum",
        "name":     "Learning Momentum",
        "keywords": ["read", "program", "code", "study", "learn"],
        "bonus":    "+25% XP · Skill XP doubled for 24h",
        "days":     1,
    },
    {
        "key":      "creative_flow",
        "name":     "Creative Flow",
        "keywords": ["write", "draw", "music", "piano", "guitar", "art", "creat"],
        "bonus":    "+20% XP · Creative domain XP boosted",
        "days":     1,
    },
    {
        "key":      "warrior_protocol",
        "name":     "Warrior Protocol",
        "keywords": ["exercise", "workout", "run", "gym", "cold", "fast"],
        "bonus":    "+30% XP · Boss battle difficulty reduced",
        "days":     1,
    },
]

TOKEN_COSTS = {
    "restore":      1,   # Restore a missed day
    "skip":         1,   # Skip today without breaking streak
    "freeze":       2,   # Freeze streak for 3 days
    "reroll":       1,   # Reroll today's daily quest
    "bonus_xp":     1,   # +50% XP for next log
    "boss_reduce":  2,   # Reduce weekly boss difficulty
    "quest_recover":2,   # Recover a failed weekly quest
}

# ── Node → Domain lookup ──────────────────────────────────────────────────

def _domain_for_skill_tree(skill_tree: str) -> str:
    """Map skill tree key → domain name."""
    for domain, defn in DOMAIN_DEFINITIONS.items():
        if skill_tree in defn.get("skill_keys", []):
            return domain
    return "Personal Growth"

def _node_name(skill_tree: str, node_id: str) -> str:
    """Resolve a human-readable node name from tree + node_id."""
    tree = SKILL_TREES.get(skill_tree, {})
    for n in tree.get("nodes", []):
        if n["id"] == node_id:
            return n["name"]
    return node_id

def _all_skill_nodes_flat() -> list[dict]:
    """Flat list of {tree, node_id, name, domain} for the habit-creation picker."""
    result = []
    for tree_key, tree_def in SKILL_TREES.items():
        domain = _domain_for_skill_tree(tree_key)
        for node in tree_def.get("nodes", []):
            result.append({
                "tree":   tree_key,
                "id":     node["id"],
                "name":   node["name"],
                "domain": domain,
                "icon":   tree_def.get("icon", ""),
                "color":  tree_def.get("color", ""),
            })
    return result

# ── XP Modifiers ──────────────────────────────────────────────────────────

def _compute_xp(
    habit_name: str,
    base_xp: int,
    streak: int,
    today: str,
    domain: str,
    first_today: bool,
    ai_recommended: bool = False,
) -> tuple[int, list[dict]]:
    """Compute final XP with all modifiers. Returns (total_xp, modifiers_list)."""
    mods = []
    total = base_xp

    # Morning completion (before 10am UTC)
    hour = datetime.now(timezone.utc).hour
    if hour < 10:
        bonus = round(base_xp * 0.25)
        mods.append({"key": "morning", "label": "☀️ Morning", "bonus": bonus})
        total += bonus

    # First habit of the day
    if first_today:
        bonus = round(base_xp * 0.15)
        mods.append({"key": "first_habit", "label": "⚡ First Today", "bonus": bonus})
        total += bonus

    # Perfect week (7-day streak)
    if streak > 0 and streak % 7 == 0:
        bonus = round(base_xp * 0.5)
        mods.append({"key": "perfect_week", "label": "🔥 Perfect Week", "bonus": bonus})
        total += bonus

    # AI recommended
    if ai_recommended:
        bonus = round(base_xp * 0.3)
        mods.append({"key": "ai_rec", "label": "✦ AI Recommended", "bonus": bonus})
        total += bonus

    # Domain underdeveloped — check if domain has low XP
    try:
        dom_defn = DOMAIN_DEFINITIONS.get(domain, {})
        dom_cats = set(dom_defn.get("skill_keys", []) + dom_defn.get("goal_cats", []))
        dom_xp = sum(get_category_xp(c) for c in dom_cats)
        all_xp = get_total_xp()
        if all_xp > 0 and dom_xp / all_xp < 0.1:  # less than 10% share
            bonus = round(base_xp * 0.4)
            mods.append({"key": "underdog", "label": "📈 Domain Boost", "bonus": bonus})
            total += bonus
    except Exception:
        pass

    # Active synergy bonus from today
    try:
        synergies = supabase.table("habit_synergies").select("key").eq("earned_at", today).execute().data
        if synergies:
            bonus = round(base_xp * 0.2)
            mods.append({"key": "synergy", "label": "⚗️ Synergy Active", "bonus": bonus})
            total += bonus
    except Exception:
        pass

    # Bonus XP token active
    try:
        bonus_token = supabase.table("habit_recovery_tokens_v2").select("id").eq("habit_name", habit_name).eq("token_type", "bonus_xp").is_("used_at", None).limit(1).execute().data
        if bonus_token:
            bonus = round(base_xp * 0.5)
            mods.append({"key": "token_bonus", "label": "🛡️ XP Token", "bonus": bonus})
            total += bonus
            # Mark used
            supabase.table("habit_recovery_tokens_v2").update({"used_at": datetime.now(timezone.utc).isoformat()}).eq("id", bonus_token[0]["id"]).execute()
    except Exception:
        pass

    return max(total, base_xp), mods

# ── Synergy Detection ─────────────────────────────────────────────────────

def _detect_synergies(habits_logged_today: list[str], today: str) -> list[dict]:
    """Check if today's habit completions triggered any synergies."""
    combined = " ".join(h.lower() for h in habits_logged_today)
    new_synergies = []
    for rule in SYNERGY_RULES:
        keywords_hit = sum(1 for kw in rule["keywords"] if kw in combined)
        if keywords_hit >= 2:
            # Check not already awarded today
            try:
                existing = supabase.table("habit_synergies").select("id").eq("synergy_key", rule["key"]).eq("earned_at", today).execute()
                if existing.data:
                    continue
            except Exception:
                pass
            expires = (datetime.now(timezone.utc) + timedelta(days=rule["days"])).strftime("%Y-%m-%d")
            try:
                supabase.table("habit_synergies").insert({
                    "synergy_key":     rule["key"],
                    "name":            rule["name"],
                    "bonus_desc":      rule["bonus"],
                    "habits_involved": habits_logged_today,
                    "earned_at":       today,
                    "expires_at":      expires,
                }).execute()
            except Exception:
                pass
            new_synergies.append({"name": rule["name"], "bonus": rule["bonus"]})
    return new_synergies

# ── Mastery + Evolution ───────────────────────────────────────────────────

def _mastery(total: int) -> dict:
    level, label = 1, "Beginner"
    for i, (threshold, lbl) in enumerate(MASTERY_LEVELS):
        if total >= threshold:
            level, label = i + 1, lbl
    return {"level": level, "label": label}

def _evolution_stage_index(total: int) -> int:
    """Which evolution threshold has been reached (0-based)."""
    for i, t in enumerate(EVOLUTION_THRESHOLDS):
        if total < t:
            return i
    return len(EVOLUTION_THRESHOLDS)

def _check_evolution_ready(name: str, total: int) -> Optional[dict]:
    """Returns evolution proposal if the habit just hit a threshold."""
    for threshold in EVOLUTION_THRESHOLDS:
        if total == threshold:
            return {
                "ready":     True,
                "threshold": threshold,
                "message":   f"After {total} completions, '{name}' is ready to evolve.",
            }
    return None

def _get_or_create_profile(name: str, skill_node_id: str = "", skill_tree: str = "", domain: str = "") -> dict:
    """Fetch habit profile, creating it if absent."""
    try:
        result = supabase.table("habit_profiles").select("*").eq("name", name).limit(1).execute()
        if result.data:
            return result.data[0]
    except Exception:
        pass
    # Create a minimal profile
    base_xp = 10
    new_profile = {
        "name":             name,
        "skill_node_id":    skill_node_id,
        "skill_tree":       skill_tree,
        "domain":           domain or _domain_for_skill_tree(skill_tree) if skill_tree else "Personal Growth",
        "evolution_stage":  1,
        "evolution_stages": [],
        "pending_evolution": False,
        "base_xp":          base_xp,
    }
    try:
        r = supabase.table("habit_profiles").insert(new_profile).execute()
        return r.data[0] if r.data else new_profile
    except Exception:
        return new_profile

# ── Recovery Tokens ───────────────────────────────────────────────────────

def _count_tokens(habit_name: str) -> dict:
    """Count earned vs used tokens for a habit."""
    try:
        # Earned: 1 per 14-day streak segment (legacy formula)
        log = supabase.table("habits").select("completed_at").eq("name", habit_name).execute()
        dates_asc = sorted({r["completed_at"] for r in log.data})
        earned = _recovery_tokens_from_dates(dates_asc)

        # Used V2 tokens
        used_rows = supabase.table("habit_recovery_tokens_v2").select("token_type").eq("habit_name", habit_name).execute().data
        used_count = len(used_rows)

        available = max(0, earned - used_count)
        return {"earned": earned, "used": used_count, "available": available, "history": used_rows}
    except Exception:
        return {"earned": 0, "used": 0, "available": 0, "history": []}

# ── Full Habit Snapshot ───────────────────────────────────────────────────

def _build_habit_snapshot(name: str, profile: dict, dates_desc: list[str], today: str) -> dict:
    """Build the rich habit card data for the frontend."""
    total   = len(dates_desc)
    streak  = calc_streak(dates_desc, today)
    mastery = _mastery(total)
    tokens  = _count_tokens(name)

    # Success rate: completed days / days since first log
    try:
        if dates_desc:
            first = datetime.strptime(dates_desc[-1], "%Y-%m-%d")
            days_active = (datetime.now(timezone.utc).replace(tzinfo=None) - first).days + 1
            success_rate = round(total / max(days_active, 1) * 100)
        else:
            success_rate = 0
    except Exception:
        success_rate = 0

    # Best streak
    best_streak = 0
    if dates_desc:
        cur = 1
        best_streak = 1
        for i in range(1, len(dates_desc)):
            try:
                a = datetime.strptime(dates_desc[i-1], "%Y-%m-%d")
                b = datetime.strptime(dates_desc[i],   "%Y-%m-%d")
                if (a - b).days == 1:
                    cur += 1
                    best_streak = max(best_streak, cur)
                else:
                    cur = 1
            except Exception:
                cur = 1

    # Evolution info
    stage_idx      = _evolution_stage_index(total)
    stages         = profile.get("evolution_stages") or []
    current_stage  = stages[profile.get("evolution_stage", 1) - 1] if stages else {}
    next_threshold = EVOLUTION_THRESHOLDS[stage_idx] if stage_idx < len(EVOLUTION_THRESHOLDS) else None
    progress_to_next = round(total / next_threshold * 100) if next_threshold else 100

    # Active synergies
    try:
        active_syn = supabase.table("habit_synergies").select("name, bonus_desc").gte("expires_at", today).execute().data
    except Exception:
        active_syn = []

    return {
        "name":              name,
        "skill_node_id":     profile.get("skill_node_id", ""),
        "skill_node_name":   _node_name(profile.get("skill_tree", ""), profile.get("skill_node_id", "")),
        "skill_tree":        profile.get("skill_tree", ""),
        "domain":            profile.get("domain", ""),
        "base_xp":           profile.get("base_xp", 10),
        # Streak / mastery
        "current_streak":    streak,
        "best_streak":       best_streak,
        "total_logs":        total,
        "success_rate":      success_rate,
        "done_today":        today in dates_desc,
        "mastery_level":     mastery["level"],
        "mastery_label":     mastery["label"],
        # Evolution
        "evolution_stage":      profile.get("evolution_stage", 1),
        "evolution_stages":     stages,
        "pending_evolution":    profile.get("pending_evolution", False),
        "progress_to_next_evo": progress_to_next,
        "next_evo_at":          next_threshold,
        # Tokens
        "recovery_tokens":   tokens,
        # Synergies
        "active_synergies":  active_syn,
        # Legacy compat
        "category":          profile.get("domain", "Personal Growth"),
        "difficulty":        "Normal",
        "xp_per_log":        profile.get("base_xp", 10),
    }

# ── Legacy helpers (kept for backwards compat calls) ─────────────────────

def _compute_streaks_raw() -> dict:
    """Returns the streaks dict expected by AI insight, insights page, etc."""
    try:
        log = supabase.table("habits").select("name, completed_at").order("completed_at", desc=True).execute()
        habit_dates: dict[str, list] = defaultdict(list)
        for row in log.data:
            habit_dates[row["name"]].append(row["completed_at"])
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        profiles = {r["name"]: r for r in supabase.table("habit_profiles").select("*").execute().data}
        out = {}
        for name, dates in habit_dates.items():
            unique_desc = sorted(set(dates), reverse=True)
            prof = profiles.get(name, {})
            snap = _build_habit_snapshot(name, prof, unique_desc, today)
            out[name] = snap
        return out
    except Exception:
        return {}

def _build_life_balance(streaks: dict) -> list[dict]:
    """Domain-based balance (replaces old category-based balance)."""
    start14 = (datetime.now(timezone.utc) - timedelta(days=14)).strftime("%Y-%m-%d")
    expected = 14
    by_domain: dict[str, list] = defaultdict(list)
    try:
        log = supabase.table("habits").select("name, completed_at").gte("completed_at", start14).execute()
        profiles = {r["name"]: r for r in supabase.table("habit_profiles").select("name, domain").execute().data}
        for row in log.data:
            dom = profiles.get(row["name"], {}).get("domain") or "Personal Growth"
            by_domain[dom].append(row["completed_at"])
    except Exception:
        pass
    all_domains = list(DOMAIN_DEFINITIONS.keys())
    out = []
    for dom in all_domains:
        dates  = by_domain.get(dom, [])
        unique = len(set(dates))
        rate   = round(unique / expected * 100)
        out.append({"category": dom, "rate": min(rate, 100), "logs": unique})
    return out

def _build_habit_heatmap(days: int = 365) -> list[dict]:
    start = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    try:
        result = supabase.table("habits").select("completed_at").gte("completed_at", start).execute()
        counts: dict[str, int] = defaultdict(int)
        for row in result.data:
            counts[row["completed_at"]] += 1
        return [{"date": d, "count": c} for d, c in sorted(counts.items())]
    except Exception:
        return []

# ── Quest Generation from Habits ─────────────────────────────────────────

def _generate_habit_quest(habit_name: str, skill_node_name: str, domain: str, stage: int) -> Optional[dict]:
    """AI generates a specific daily/weekly quest from this habit."""
    try:
        prompt = f"""You generate quests for a personal growth RPG.

Habit: "{habit_name}"
Skill Node: "{skill_node_name}"
Domain: "{domain}"
Evolution Stage: {stage}

Generate ONE concrete, achievable quest for today tied to this habit.
Stage 1 = beginner (5-10 min), Stage 3+ = intermediate (20-30 min).

Reply ONLY in JSON (no markdown):
{{
  "title": "specific action under 10 words",
  "description": "one sentence describing what to do",
  "duration_minutes": a number,
  "difficulty": "Easy|Normal|Hard"
}}"""
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7, max_tokens=150,
        )
        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = "\n".join(raw.split("\n")[1:]).replace("```", "")
        return _json.loads(raw.strip())
    except Exception:
        return None

def _generate_evolution_stages(habit_name: str, skill_node_name: str) -> list[dict]:
    """AI generates 5 evolution stages for a habit."""
    try:
        prompt = f"""You design habit evolution for a personal growth RPG.

Habit: "{habit_name}"
Skill Node: "{skill_node_name}"

Design 5 progressive evolution stages. Each stage increases difficulty/depth.

Reply ONLY in JSON array (no markdown):
[
  {{"stage": 1, "title": "short name", "description": "what this stage looks like", "duration_minutes": 5}},
  {{"stage": 2, "title": "...", "description": "...", "duration_minutes": 10}},
  {{"stage": 3, "title": "...", "description": "...", "duration_minutes": 20}},
  {{"stage": 4, "title": "...", "description": "...", "duration_minutes": 30}},
  {{"stage": 5, "title": "...", "description": "...", "duration_minutes": 45}}
]"""
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.6, max_tokens=400,
        )
        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = "\n".join(raw.split("\n")[1:]).replace("```", "")
        return _json.loads(raw.strip())
    except Exception:
        return []

def _ai_adapt_habit(habit_name: str, success_rate: int, streak: int, stage: int) -> Optional[str]:
    """Returns adaptation suggestion if habit is struggling or thriving."""
    if success_rate >= 70 and streak >= 7:
        direction = "evolve"
    elif success_rate < 40:
        direction = "simplify"
    else:
        return None
    try:
        prompt = f"""Habit: "{habit_name}", success rate: {success_rate}%, streak: {streak} days, stage: {stage}.
Direction: {direction}.
Give ONE sentence of specific advice (max 20 words). {"Recommend a harder version." if direction=="evolve" else "Recommend a simpler version to rebuild momentum."}"""
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7, max_tokens=60,
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return None

# ── Endpoints ─────────────────────────────────────────────────────────────

@app.get("/habits/skill-nodes")
def get_habit_skill_nodes():
    """All skill nodes available for linking to habits."""
    return _all_skill_nodes_flat()

@app.post("/habits/profile")
def create_habit_profile(req: HabitCreate):
    """Create or update a habit profile (links habit → skill node)."""
    node_name = _node_name(req.skill_tree, req.skill_node_id)
    domain    = _domain_for_skill_tree(req.skill_tree)
    stages    = _generate_evolution_stages(req.name, node_name)
    base_xp   = 10  # starts small; modifiers do the work

    try:
        existing = supabase.table("habit_profiles").select("id").eq("name", req.name).execute()
        if existing.data:
            supabase.table("habit_profiles").update({
                "skill_node_id":   req.skill_node_id,
                "skill_tree":      req.skill_tree,
                "domain":          domain,
                "evolution_stages": stages,
                "updated_at":      datetime.now(timezone.utc).isoformat(),
            }).eq("name", req.name).execute()
        else:
            supabase.table("habit_profiles").insert({
                "name":             req.name,
                "skill_node_id":    req.skill_node_id,
                "skill_tree":       req.skill_tree,
                "domain":           domain,
                "evolution_stages": stages,
                "evolution_stage":  1,
                "pending_evolution": False,
                "base_xp":          base_xp,
            }).execute()
    except Exception as e:
        raise HTTPException(500, str(e))

    return {"status": "ok", "domain": domain, "node_name": node_name, "stages": stages}

@app.post("/habits")
def log_habit(habit: HabitLog):
    """Log a habit completion with full V2 enrichment."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Idempotent
    existing = supabase.table("habits").select("id").eq("name", habit.name).eq("completed_at", today).execute()
    if existing.data:
        return {"status": "already_logged", "message": f"'{habit.name}' already logged today."}

    # Resolve profile
    profile = _get_or_create_profile(
        habit.name,
        habit.skill_node_id or "",
        habit.skill_tree or habit.linked_skill or "",
        _domain_for_skill_tree(habit.skill_tree or habit.linked_skill or ""),
    )
    skill_tree     = profile.get("skill_tree") or habit.skill_tree or habit.linked_skill or ""
    skill_node_id  = profile.get("skill_node_id") or habit.skill_node_id or ""
    domain         = profile.get("domain") or _domain_for_skill_tree(skill_tree)
    base_xp        = profile.get("base_xp") or 10

    # Check if first habit logged today
    already_today = supabase.table("habits").select("id").eq("completed_at", today).execute()
    first_today   = len(already_today.data) == 0

    # Get current streak for modifier
    all_dates_desc = sorted(
        {r["completed_at"] for r in supabase.table("habits").select("completed_at").eq("name", habit.name).execute().data},
        reverse=True
    )
    streak = calc_streak(all_dates_desc, today)

    xp_total, modifiers = _compute_xp(habit.name, base_xp, streak, today, domain, first_today)

    # Insert log row — only use columns that exist in the base schema
    result = supabase.table("habits").insert({
        "name":         habit.name,
        "completed_at": today,
        "created_at":   datetime.now(timezone.utc).isoformat(),
    }).execute()

    # XP to ledger — domain and skill tree both
    ledger_add("habit", f"{habit.name}:{today}", "Personal Growth", xp_total)
    if skill_tree and skill_tree in SKILL_TREES:
        ledger_add("habit_skill", f"{habit.name}:{today}:skill", skill_tree, xp_total)

    # Skill node XP contribution
    if skill_node_id and skill_tree:
        ledger_add("habit_node", f"{habit.name}:{today}:{skill_node_id}", skill_tree, round(xp_total * 0.5))

    # Updated streak/totals
    all_dates_desc = sorted(
        {r["completed_at"] for r in supabase.table("habits").select("completed_at").eq("name", habit.name).execute().data},
        reverse=True
    )
    total  = len(all_dates_desc)
    streak = calc_streak(all_dates_desc, today)

    # Synergy detection
    today_habits = [r["name"] for r in supabase.table("habits").select("name").eq("completed_at", today).execute().data]
    new_synergies = _detect_synergies(today_habits, today)

    # Evolution check
    evo_ready = _check_evolution_ready(habit.name, total)
    if evo_ready:
        try:
            supabase.table("habit_profiles").update({"pending_evolution": True}).eq("name", habit.name).execute()
        except Exception:
            pass

    # Generate a habit quest (non-blocking, best-effort)
    habit_quest = None
    try:
        node_name   = _node_name(skill_tree, skill_node_id)
        habit_quest = _generate_habit_quest(habit.name, node_name, domain, profile.get("evolution_stage", 1))
        # Auto-create quest if we have a matching goal
        if habit_quest:
            goal_data = build_goal_summary()
            cat_goal  = next((g for g in goal_data if g.get("category") == skill_tree), None)
            if cat_goal:
                supabase.table("quests").insert({
                    "goal_id":      cat_goal["id"],
                    "title":        habit_quest["title"],
                    "description":  habit_quest.get("description", ""),
                    "difficulty":   habit_quest.get("difficulty", "Normal"),
                    "is_completed": False,
                    "created_at":   datetime.now(timezone.utc).isoformat(),
                }).execute()
    except Exception:
        pass

    # Adaptation advice
    mastery    = _mastery(total)
    snap       = _build_habit_snapshot(habit.name, profile, all_dates_desc, today)
    adaptation = _ai_adapt_habit(habit.name, snap["success_rate"], streak, profile.get("evolution_stage", 1))

    new_achievements = award_achievements()

    return {
        "status":          "logged",
        "xp_earned":       xp_total,
        "xp_modifiers":    modifiers,
        "streak":          streak,
        "total_logs":      total,
        "mastery":         mastery,
        "evolution_ready": evo_ready,
        "new_synergies":   new_synergies,
        "habit_quest":     habit_quest,
        "adaptation":      adaptation,
        "new_achievements": new_achievements,
        "domain":          domain,
        "skill_tree":      skill_tree,
    }

@app.get("/habits/streaks")
def get_streaks():
    return _compute_streaks_raw()

@app.get("/habits/heatmap")
def get_heatmap(days: int = 365):
    return _build_habit_heatmap(days)

@app.get("/habits/balance")
def get_life_balance():
    try:    streaks = _compute_streaks_raw()
    except: streaks = {}
    try:    balance = _build_life_balance(streaks)
    except: balance = [{"category": d, "rate": 0, "logs": 0} for d in DOMAIN_DEFINITIONS]
    return {"balance": balance, "streaks": streaks}

@app.get("/habits/stats/{habit_name}")
def get_habit_stats(habit_name: str):
    """Full lifetime statistics for one habit."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log   = supabase.table("habits").select("completed_at").eq("name", habit_name).execute()
    dates_desc = sorted({r["completed_at"] for r in log.data}, reverse=True)
    profile    = _get_or_create_profile(habit_name)
    snap       = _build_habit_snapshot(habit_name, profile, dates_desc, today)

    # Milestones reached
    milestones = []
    for threshold in EVOLUTION_THRESHOLDS:
        if snap["total_logs"] >= threshold:
            milestones.append({"at": threshold, "reached": True})
        else:
            milestones.append({"at": threshold, "reached": False, "remaining": threshold - snap["total_logs"]})

    # Total XP earned from ledger (base_xp * total_logs as fallback)
    base_xp = profile.get("base_xp") or 10
    total_xp = base_xp * len(dates_desc)

    # Heatmap for this specific habit
    heatmap_counts: dict[str, int] = defaultdict(int)
    for row in log.data:
        heatmap_counts[row["completed_at"]] += 1
    heatmap = [{"date": d, "count": c} for d, c in sorted(heatmap_counts.items())]

    return {
        **snap,
        "total_xp_earned": total_xp,
        "milestones":      milestones,
        "heatmap":         heatmap,
        "evolution_stages": profile.get("evolution_stages") or [],
    }

@app.post("/habits/{habit_name}/evolve")
def confirm_evolution(habit_name: str, req: EvolutionConfirm):
    """User confirms (or rejects) an evolution proposal."""
    if not req.confirmed:
        supabase.table("habit_profiles").update({"pending_evolution": False}).eq("name", habit_name).execute()
        return {"status": "declined"}

    profile = _get_or_create_profile(habit_name)
    current_stage = profile.get("evolution_stage", 1)
    stages        = profile.get("evolution_stages") or []
    new_stage     = min(current_stage + 1, 5)

    # If user provided a custom title, update that stage
    if req.new_stage_title and stages and len(stages) >= new_stage:
        stages[new_stage - 1]["title"] = req.new_stage_title

    # Bump base XP with evolution
    new_base_xp = round(profile.get("base_xp", 10) * 1.4)

    supabase.table("habit_profiles").update({
        "evolution_stage":  new_stage,
        "evolution_stages": stages,
        "pending_evolution": False,
        "base_xp":          new_base_xp,
        "updated_at":       datetime.now(timezone.utc).isoformat(),
    }).eq("name", habit_name).execute()

    # Bonus XP for evolving
    ledger_add("habit_evolution", f"{habit_name}:stage{new_stage}", "Personal Growth", 100)

    return {
        "status":     "evolved",
        "new_stage":  new_stage,
        "new_base_xp": new_base_xp,
        "xp_bonus":   100,
    }

@app.post("/habits/recover")
def use_recovery_token(req: RecoveryTokenUse):
    """Spend a recovery token. Type determines effect."""
    tokens = _count_tokens(req.name)
    cost   = TOKEN_COSTS.get(req.token_type, 1)
    if tokens["available"] < cost:
        raise HTTPException(400, f"Need {cost} token(s), have {tokens['available']}.")

    for _ in range(cost):
        supabase.table("habit_recovery_tokens_v2").insert({
            "habit_name": req.name,
            "token_type": req.token_type,
            "meta":       {"date": req.date},
            "used_at":    datetime.now(timezone.utc).isoformat(),
        }).execute()

    effect = {}

    if req.token_type == "restore":
        # Insert a recovered completion using only base schema columns
        supabase.table("habits").insert({
            "name":         req.name,
            "completed_at": req.date,
            "created_at":   datetime.now(timezone.utc).isoformat(),
        }).execute()
        effect = {"restored_date": req.date, "message": "Missed day restored — streak protected."}

    elif req.token_type == "boss_reduce":
        effect = {"message": "Next boss difficulty will be reduced when generated."}

    elif req.token_type == "quest_recover":
        effect = {"message": "Your failed quest has been recovered and reset."}

    elif req.token_type == "bonus_xp":
        effect = {"message": "+50% XP on your next habit log."}

    elif req.token_type == "freeze":
        effect = {"message": "Streak frozen for 3 days."}

    elif req.token_type == "reroll":
        effect = {"message": "Daily quest rerolled."}

    return {"status": "used", "token_type": req.token_type, "effect": effect, "remaining": tokens["available"] - cost}

class HabitUpdate(BaseModel):
    new_name: str = ""
    skill_node_id: str = ""
    skill_tree: str = ""

@app.delete("/habits/{habit_name}")
def delete_habit(habit_name: str):
    """Delete a habit and all its history (logs, profile, tokens, synergies)."""
    # Delete all log rows
    supabase.table("habits").delete().eq("name", habit_name).execute()
    # Delete profile
    try:
        supabase.table("habit_profiles").delete().eq("name", habit_name).execute()
    except Exception:
        pass
    # Delete recovery tokens
    try:
        supabase.table("habit_recovery_tokens_v2").delete().eq("habit_name", habit_name).execute()
    except Exception:
        pass
    # Delete any XP ledger entries for this habit
    try:
        supabase.table("xp_ledger").delete().eq("source_type", "habit").like("source_id", f"{habit_name}:%").execute()
        supabase.table("xp_ledger").delete().eq("source_type", "habit_skill").like("source_id", f"{habit_name}:%").execute()
        supabase.table("xp_ledger").delete().eq("source_type", "habit_node").like("source_id", f"{habit_name}:%").execute()
    except Exception:
        pass
    return {"status": "deleted", "name": habit_name}

@app.put("/habits/{habit_name}")
def update_habit(habit_name: str, req: HabitUpdate):
    """Rename a habit and/or relink it to a different skill node."""
    new_name = req.new_name.strip() if req.new_name.strip() else habit_name

    # Rename all log rows if name changed
    if new_name != habit_name:
        existing = supabase.table("habits").select("id").eq("name", new_name).execute()
        if existing.data:
            raise HTTPException(400, f"A habit named '{new_name}' already exists.")
        supabase.table("habits").update({"name": new_name}).eq("name", habit_name).execute()
        try:
            supabase.table("habit_recovery_tokens_v2").update({"habit_name": new_name}).eq("habit_name", habit_name).execute()
        except Exception:
            pass

    # Update or create profile with new name / skill node
    node_name = _node_name(req.skill_tree, req.skill_node_id) if req.skill_node_id else ""
    domain    = _domain_for_skill_tree(req.skill_tree) if req.skill_tree else ""

    try:
        existing_profile = supabase.table("habit_profiles").select("id").eq("name", habit_name).execute()
        update_data = {"name": new_name}
        if req.skill_node_id:
            update_data["skill_node_id"] = req.skill_node_id
            update_data["skill_tree"]    = req.skill_tree
            update_data["domain"]        = domain
            # Regenerate evolution stages if node changed
            stages = _generate_evolution_stages(new_name, node_name)
            update_data["evolution_stages"] = stages
        if existing_profile.data:
            supabase.table("habit_profiles").update(update_data).eq("name", habit_name).execute()
        else:
            supabase.table("habit_profiles").insert({
                **update_data,
                "skill_node_id":  req.skill_node_id or "",
                "skill_tree":     req.skill_tree or "",
                "domain":         domain or "Personal Growth",
                "evolution_stage": 1,
                "pending_evolution": False,
                "base_xp": 10,
            }).execute()
    except Exception as e:
        raise HTTPException(500, str(e))

    return {
        "status":    "updated",
        "old_name":  habit_name,
        "new_name":  new_name,
        "node_name": node_name,
        "domain":    domain,
    }

@app.get("/habits/ai-insights")
def habit_ai_insights():
    streaks  = _compute_streaks_raw()
    if not streaks:
        return {"insight": "Log some habits first to unlock AI habit insights."}
    balance  = _build_life_balance(streaks)
    entries  = fetch_all_entries_light()

    mood_by_date: dict[str, list] = defaultdict(list)
    for e in entries:
        mood_by_date[e["created_at"][:10]].append(e["mood"])
    habit_result   = supabase.table("habits").select("name, completed_at").execute()
    habits_by_date: dict[str, list] = defaultdict(list)
    for r in habit_result.data:
        habits_by_date[r["completed_at"]].append(r["name"])

    moods_with, moods_without = [], []
    for date, moods in mood_by_date.items():
        (moods_with if habits_by_date.get(date) else moods_without).extend(moods)

    avg_with    = round(sum(moods_with)    / len(moods_with),    1) if moods_with    else None
    avg_without = round(sum(moods_without) / len(moods_without), 1) if moods_without else None
    strongest   = max(streaks.items(), key=lambda x: x[1]["current_streak"], default=(None, {}))
    weakest     = min(streaks.items(), key=lambda x: x[1]["current_streak"], default=(None, {}))

    # Adaptation signals
    adapt_signals = []
    for name, data in streaks.items():
        sr = data.get("success_rate", 0)
        if sr < 40:
            adapt_signals.append(f"'{name}' struggling ({sr}% success rate)")
        elif sr > 80 and data.get("current_streak", 0) > 7:
            adapt_signals.append(f"'{name}' thriving — consider evolving")

    prompt = f"""You are LiAInne analyzing habit data for a personal growth RPG.

Habits: {_json.dumps({k: {"streak": v["current_streak"], "total": v["total_logs"], "domain": v.get("domain","?"), "success_rate": v.get("success_rate",0)} for k,v in streaks.items()})}
Domain balance (14 days): {_json.dumps(balance)}
Strongest: {strongest[0]} ({strongest[1].get("current_streak",0)}-day streak)
Adaptation signals: {adapt_signals}
Mood on habit days: {avg_with}/5 vs no-habit days: {avg_without}/5

Write 2-3 sharp observations (max 80 words). Be specific, name habits, mention domains. No generic advice."""

    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.8, max_tokens=150,
    )
    return {
        "insight":              response.choices[0].message.content,
        "mood_with_habits":     avg_with,
        "mood_without_habits":  avg_without,
        "strongest":            strongest[0],
        "adaptation_signals":   adapt_signals,
    }
# ---------------------------------------------------------------------------
# Goals V2 — 4-tier hierarchy: Goal → Milestone → Quest → Task
# Progress rolls up automatically: tasks → quests → milestones → goals
# ---------------------------------------------------------------------------

class QuestCreate(BaseModel):
    title: str
    description: str = ""
    difficulty: str = "Normal"
    milestone_id: Optional[int] = None

class TaskCreateV2(BaseModel):
    title: str
    quest_id: Optional[int] = None  # None = legacy direct-to-goal task


# ---------------------------------------------------------------------------
# Progress rollup helpers
# ---------------------------------------------------------------------------

def _rollup_quest(quest_id: int) -> dict:
    """Recompute quest.is_completed from its tasks and save to DB."""
    tasks = supabase.table("goal_tasks").select("is_completed").eq("quest_id", quest_id).execute().data
    if not tasks:
        return {"quest_id": quest_id, "is_completed": False, "progress": 0}
    total     = len(tasks)
    completed = sum(1 for t in tasks if t["is_completed"])
    progress  = round(completed / total * 100) if total else 0
    done      = completed == total and total > 0
    supabase.table("quests").update({"is_completed": done}).eq("id", quest_id).execute()
    return {"quest_id": quest_id, "is_completed": done, "progress": progress,
            "completed_tasks": completed, "total_tasks": total}

def _rollup_milestone(milestone_id: int) -> dict:
    """Recompute milestone.is_completed from its quests and save to DB."""
    quests = supabase.table("quests").select("is_completed").eq("milestone_id", milestone_id).execute().data
    if not quests:
        return {"milestone_id": milestone_id, "is_completed": False, "progress": 0}
    total     = len(quests)
    completed = sum(1 for q in quests if q["is_completed"])
    progress  = round(completed / total * 100) if total else 0
    done      = completed == total and total > 0
    if done:
        # Award milestone XP — get goal's category
        ms = supabase.table("goal_milestones").select("goal_id, is_completed").eq("id", milestone_id).single().execute().data
        if ms and not ms["is_completed"]:
            goal = supabase.table("goals").select("category").eq("id", ms["goal_id"]).single().execute().data
            cat  = goal.get("category", "Personal Growth") if goal else "Personal Growth"
            ledger_add("milestone", str(milestone_id), cat, 75)
            award_achievements()
    supabase.table("goal_milestones").update({"is_completed": done}).eq("id", milestone_id).execute()
    return {"milestone_id": milestone_id, "is_completed": done, "progress": progress}

def _rollup_goal(goal_id: int) -> dict:
    """
    Goal progress = weighted average:
      - If goal has milestones: milestone completion rate
      - Else if goal has quests: quest completion rate
      - Else: direct task completion rate (legacy)
    Never writes to DB — goals don't have a stored progress field.
    """
    milestones = supabase.table("goal_milestones").select("is_completed").eq("goal_id", goal_id).execute().data
    if milestones:
        total     = len(milestones)
        completed = sum(1 for m in milestones if m["is_completed"])
        return {"progress": round(completed / total * 100) if total else 0,
                "completed": completed, "total": total, "basis": "milestones"}

    quests = supabase.table("quests").select("is_completed").eq("goal_id", goal_id).execute().data
    if quests:
        total     = len(quests)
        completed = sum(1 for q in quests if q["is_completed"])
        return {"progress": round(completed / total * 100) if total else 0,
                "completed": completed, "total": total, "basis": "quests"}

    # Legacy: direct tasks
    tasks = supabase.table("goal_tasks").select("is_completed").eq("goal_id", goal_id).is_("quest_id", "null").execute().data
    total     = len(tasks)
    completed = sum(1 for t in tasks if t["is_completed"])
    return {"progress": round(completed / total * 100) if total else 0,
            "completed": completed, "total": total, "basis": "tasks"}


# ---------------------------------------------------------------------------
# Full goal summary builder (V2)
# ---------------------------------------------------------------------------

def build_goal_summary() -> list[dict]:
    goals     = supabase.table("goals").select("*").order("created_at", desc=True).execute().data
    all_ms    = supabase.table("goal_milestones").select("*").execute().data
    all_q     = supabase.table("quests").select("*").execute().data
    all_tasks = supabase.table("goal_tasks").select("*").execute().data

    # Index everything
    ms_by_goal: dict[int, list] = defaultdict(list)
    for ms in all_ms:
        ms_by_goal[ms["goal_id"]].append(ms)

    q_by_goal: dict[int, list] = defaultdict(list)
    q_by_ms:   dict[int, list] = defaultdict(list)
    for q in all_q:
        q_by_goal[q["goal_id"]].append(q)
        if q.get("milestone_id"):
            q_by_ms[q["milestone_id"]].append(q)

    tasks_by_quest: dict[int, list] = defaultdict(list)
    tasks_by_goal:  dict[int, list] = defaultdict(list)  # legacy direct tasks
    for t in all_tasks:
        if t.get("quest_id"):
            tasks_by_quest[t["quest_id"]].append(t)
        else:
            tasks_by_goal[t["goal_id"]].append(t)

    summary = []
    for goal in goals:
        gid       = goal["id"]
        xp        = get_category_xp(goal["category"])
        level_info = xp_to_level(xp)
        created   = datetime.fromisoformat(goal["created_at"].replace("Z", "+00:00"))
        days_old  = (datetime.now(timezone.utc) - created).days

        # Build enriched milestones
        milestones = []
        for ms in ms_by_goal.get(gid, []):
            ms_quests = []
            for q in q_by_ms.get(ms["id"], []):
                q_tasks = tasks_by_quest.get(q["id"], [])
                q_done  = sum(1 for t in q_tasks if t["is_completed"])
                q_total = len(q_tasks)
                ms_quests.append({
                    **q,
                    "tasks":            q_tasks,
                    "completed_tasks":  q_done,
                    "total_tasks":      q_total,
                    "progress":         round(q_done / q_total * 100) if q_total else 0,
                })
            ms_q_done  = sum(1 for q in ms_quests if q["is_completed"])
            ms_q_total = len(ms_quests)
            ms_progress = round(ms_q_done / ms_q_total * 100) if ms_q_total else (100 if ms["is_completed"] else 0)
            milestones.append({
                **ms,
                "quests":           ms_quests,
                "completed_quests": ms_q_done,
                "total_quests":     ms_q_total,
                "progress":         ms_progress,
            })

        # Goal-level quests (not under any milestone)
        bare_quests = []
        for q in q_by_goal.get(gid, []):
            if q.get("milestone_id"):
                continue
            q_tasks = tasks_by_quest.get(q["id"], [])
            q_done  = sum(1 for t in q_tasks if t["is_completed"])
            q_total = len(q_tasks)
            bare_quests.append({
                **q,
                "tasks":            q_tasks,
                "completed_tasks":  q_done,
                "total_tasks":      q_total,
                "progress":         round(q_done / q_total * 100) if q_total else 0,
            })

        # Legacy direct tasks (no quest_id)
        legacy_tasks = tasks_by_goal.get(gid, [])

        # Compute goal progress
        if milestones:
            ms_done     = sum(1 for m in milestones if m["is_completed"])
            ms_total    = len(milestones)
            goal_progress = round(ms_done / ms_total * 100) if ms_total else 0
            completed_units = ms_done
            total_units     = ms_total
            progress_basis  = "milestones"
        elif bare_quests:
            q_done      = sum(1 for q in bare_quests if q["is_completed"])
            q_total     = len(bare_quests)
            goal_progress = round(q_done / q_total * 100) if q_total else 0
            completed_units = q_done
            total_units     = q_total
            progress_basis  = "quests"
        else:
            t_done      = sum(1 for t in legacy_tasks if t["is_completed"])
            t_total     = len(legacy_tasks)
            goal_progress = round(t_done / t_total * 100) if t_total else 0
            completed_units = t_done
            total_units     = t_total
            progress_basis  = "tasks"

        # For backwards-compat fields expected elsewhere
        all_tasks_flat = (
            [t for q in bare_quests for t in q["tasks"]]
            + [t for m in milestones for q in m["quests"] for t in q["tasks"]]
            + legacy_tasks
        )
        flat_done  = sum(1 for t in all_tasks_flat if t["is_completed"])
        flat_total = len(all_tasks_flat)

        summary.append({
            **goal,
            # V2 enriched
            "milestones":       milestones,
            "milestones_done":  sum(1 for m in milestones if m["is_completed"]),
            "milestones_total": len(milestones),
            "quests":           bare_quests,
            "legacy_tasks":     legacy_tasks,
            # Progress
            "progress":         goal_progress,
            "progress_basis":   progress_basis,
            "completed_units":  completed_units,
            "total_units":      total_units,
            # Legacy compat (used by domain, skill, action engine)
            "tasks":            all_tasks_flat,
            "completed_tasks":  flat_done,
            "total_tasks":      flat_total,
            # XP
            "xp":               xp,
            "level":            level_info["level"],
            "xp_in_level":      level_info["xp_in_level"],
            "xp_to_next":       level_info["xp_to_next"],
            "days_since_created": days_old,
        })
    return summary


# ---------------------------------------------------------------------------
# Goal CRUD
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

@app.get("/goals/summary")
def goals_summary():
    return build_goal_summary()

def build_category_health(summary: list[dict]) -> list[dict]:
    by_cat: dict[str, dict] = {}
    for g in summary:
        cat = g.get("category", "Other")
        by_cat.setdefault(cat, {"xp": 0, "completed": 0, "total": 0, "days": []})
        by_cat[cat]["xp"]        += g.get("xp", 0)
        by_cat[cat]["completed"] += g.get("completed_tasks", 0)
        by_cat[cat]["total"]     += g.get("total_tasks", 0)
        by_cat[cat]["days"].append(g.get("days_since_created", 0))
    health = []
    for cat, data in by_cat.items():
        rate   = round(data["completed"] / data["total"] * 100) if data["total"] > 0 else 0
        oldest = max(data["days"]) if data["days"] else 0
        stale  = oldest > 7 and rate < 50
        health.append({
            "category": cat, "total_xp": data["xp"],
            "completion_rate": rate, "stale": stale,
            "oldest_goal_days": oldest,
        })
    return sorted(health, key=lambda x: x["total_xp"], reverse=True)

@app.delete("/goals/{goal_id}")
def delete_goal(goal_id: int):
    # Cascade: tasks inside quests, quests, milestones, legacy tasks, dependencies
    quest_rows = supabase.table("quests").select("id").eq("goal_id", goal_id).execute().data
    for q in quest_rows:
        supabase.table("goal_tasks").delete().eq("quest_id", q["id"]).execute()
    supabase.table("quests").delete().eq("goal_id", goal_id).execute()
    supabase.table("goal_tasks").delete().eq("goal_id", goal_id).execute()
    supabase.table("goal_milestones").delete().eq("goal_id", goal_id).execute()
    supabase.table("goal_dependencies").delete().eq("goal_id", goal_id).execute()
    supabase.table("goal_dependencies").delete().eq("depends_on_goal_id", goal_id).execute()
    result = supabase.table("goals").delete().eq("id", goal_id).execute()
    if not result.data:
        raise HTTPException(404, "Goal not found")
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# Milestone CRUD
# ---------------------------------------------------------------------------

@app.post("/goals/{goal_id}/milestones")
def add_milestone(goal_id: int, ms: MilestoneCreate):
    result = supabase.table("goal_milestones").insert({
        "goal_id": goal_id, "title": ms.title,
        "target_date": ms.target_date,
        "is_completed": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }).execute()
    return result.data[0]

@app.delete("/milestones/{ms_id}")
def delete_milestone(ms_id: int):
    # Delete quests inside (and their tasks)
    q_rows = supabase.table("quests").select("id").eq("milestone_id", ms_id).execute().data
    for q in q_rows:
        supabase.table("goal_tasks").delete().eq("quest_id", q["id"]).execute()
    supabase.table("quests").delete().eq("milestone_id", ms_id).execute()
    supabase.table("goal_milestones").delete().eq("id", ms_id).execute()
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# Quest CRUD
# ---------------------------------------------------------------------------

@app.post("/goals/{goal_id}/quests")
def create_quest(goal_id: int, quest: QuestCreate):
    result = supabase.table("quests").insert({
        "goal_id":      goal_id,
        "milestone_id": quest.milestone_id,
        "title":        quest.title,
        "description":  quest.description,
        "difficulty":   quest.difficulty,
        "is_completed": False,
        "created_at":   datetime.now(timezone.utc).isoformat(),
    }).execute()
    return result.data[0]

@app.delete("/quests/{quest_id}")
def delete_quest(quest_id: int):
    supabase.table("goal_tasks").delete().eq("quest_id", quest_id).execute()
    result = supabase.table("quests").delete().eq("id", quest_id).execute()
    if not result.data:
        raise HTTPException(404, "Quest not found")
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# Task CRUD (V2 — tasks belong to quests; legacy tasks belong to goals)
# ---------------------------------------------------------------------------

@app.post("/quests/{quest_id}/tasks")
def create_quest_task(quest_id: int, task: TaskCreate):
    quest = supabase.table("quests").select("goal_id").eq("id", quest_id).single().execute().data
    if not quest:
        raise HTTPException(404, "Quest not found")
    result = supabase.table("goal_tasks").insert({
        "goal_id":      quest["goal_id"],
        "quest_id":     quest_id,
        "title":        task.title,
        "is_completed": False,
        "created_at":   datetime.now(timezone.utc).isoformat(),
    }).execute()
    return result.data[0]

# Legacy: direct-to-goal tasks (kept for skill-tree compat)
@app.post("/goals/{goal_id}/tasks")
def create_task(goal_id: int, task: TaskCreate):
    result = supabase.table("goal_tasks").insert({
        "goal_id":      goal_id,
        "quest_id":     None,
        "title":        task.title,
        "is_completed": False,
        "created_at":   datetime.now(timezone.utc).isoformat(),
    }).execute()
    return result.data[0]

@app.get("/goals/{goal_id}/tasks")
def get_tasks(goal_id: int):
    return supabase.table("goal_tasks").select("*").eq("goal_id", goal_id).execute().data

@app.put("/tasks/{task_id}")
def toggle_task(task_id: int):
    task = supabase.table("goal_tasks").select("*").eq("id", task_id).single().execute().data
    if not task:
        raise HTTPException(404, "Task not found")

    is_completing = not task["is_completed"]
    supabase.table("goal_tasks").update({"is_completed": is_completing}).eq("id", task_id).execute()

    rollup_result = {}
    quest_rollup  = None
    ms_rollup     = None

    if is_completing:
        goal = supabase.table("goals").select("*").eq("id", task["goal_id"]).single().execute().data
        cat  = goal.get("category", "Personal Growth") if goal else "Personal Growth"
        ledger_add("task", str(task_id), cat, XP_PER_TASK)
        new_achievements = award_achievements()

        # Rollup chain: task → quest → milestone → (goal progress is computed on read)
        if task.get("quest_id"):
            quest_rollup = _rollup_quest(task["quest_id"])
            # Find quest's milestone
            q_row = supabase.table("quests").select("milestone_id").eq("id", task["quest_id"]).single().execute().data
            if q_row and q_row.get("milestone_id"):
                ms_rollup = _rollup_milestone(q_row["milestone_id"])

        skill_completion = _auto_complete_skill_node_if_done(task["goal_id"])
        newly_unlockable = _check_new_unlocks(cat)

        return {
            "id":              task_id,
            "is_completed":    True,
            "xp_earned":       XP_PER_TASK,
            "category":        cat,
            "new_achievements": new_achievements,
            "newly_unlockable": newly_unlockable,
            "skill_completion": skill_completion,
            "quest_rollup":    quest_rollup,
            "milestone_rollup": ms_rollup,
        }

    # Unchecking — also rollup
    if task.get("quest_id"):
        quest_rollup = _rollup_quest(task["quest_id"])
        q_row = supabase.table("quests").select("milestone_id").eq("id", task["quest_id"]).single().execute().data
        if q_row and q_row.get("milestone_id"):
            ms_rollup = _rollup_milestone(q_row["milestone_id"])

    return {"id": task_id, "is_completed": False,
            "quest_rollup": quest_rollup, "milestone_rollup": ms_rollup}

@app.delete("/tasks/{task_id}")
def delete_task(task_id: int):
    task = supabase.table("goal_tasks").select("quest_id").eq("id", task_id).single().execute().data
    result = supabase.table("goal_tasks").delete().eq("id", task_id).execute()
    if not result.data:
        raise HTTPException(404, "Task not found")
    # Rollup after delete
    if task and task.get("quest_id"):
        _rollup_quest(task["quest_id"])
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# Dependencies (kept for compat)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Skill Trees
# ---------------------------------------------------------------------------

SKILL_TREES: dict[str, dict] = {
    "Study": {
        "label": "Computer Science", "icon": "📚", "color": "#6c8ebf",
        "nodes": [
            {
                "id": "cs_fundamentals", "name": "Programming Fundamentals",
                "xp_required": 0, "prerequisites": [],
                "xp_reward": 100, "difficulty": "Beginner", "estimated_hours": 5,
                "description": "Variables, loops, functions, and basic problem solving.",
                "tasks": [
                    "Understand what programming is and how computers execute code",
                    "Install a development environment (VS Code + Python)",
                    "Write your first program: Hello World",
                    "Practice variables and data types",
                    "Write a program using loops",
                    "Write a program using functions",
                    "Complete a reflection checkpoint in your journal",
                ],
                "mastery_check": {"type": "reflection", "prompt": "Describe the difference between a loop and a function. Give a real example from your own study."},
            },
            {
                "id": "cs_python", "name": "Python Basics",
                "xp_required": 100, "prerequisites": ["cs_fundamentals"],
                "xp_reward": 150, "difficulty": "Beginner", "estimated_hours": 8,
                "description": "Syntax, data types, list comprehensions, modules.",
                "tasks": [
                    "Learn Python syntax and indentation rules",
                    "Master variables and data types (int, str, list, dict)",
                    "Practice conditionals (if / elif / else)",
                    "Write programs using for and while loops",
                    "Define and call functions with parameters",
                    "Use list comprehensions",
                    "Import and use standard library modules",
                    "Build a mini project (e.g. a calculator or to-do list)",
                    "Pass the Python Basics quiz",
                ],
                "mastery_check": {"type": "challenge", "prompt": "Write (or describe from memory) a Python function that takes a list of numbers and returns only the even ones using a list comprehension."},
            },
            {
                "id": "cs_dsa", "name": "Data Structures",
                "xp_required": 200, "prerequisites": ["cs_fundamentals"],
                "xp_reward": 250, "difficulty": "Intermediate", "estimated_hours": 12,
                "description": "Arrays, linked lists, stacks, queues, hashmaps.",
                "tasks": [
                    "Understand arrays and their time complexity",
                    "Implement a singly linked list",
                    "Build a stack using a list",
                    "Build a queue using collections.deque",
                    "Understand and use hashmaps (Python dicts)",
                    "Solve 3 LeetCode Easy problems using arrays",
                    "Solve 2 LeetCode Easy problems using hashmaps",
                    "Build a mini project: implement a stack-based expression evaluator",
                    "Pass the Data Structures quiz",
                ],
                "mastery_check": {"type": "quiz", "prompt": "Explain when you'd choose a hashmap over an array. Give a concrete use case you've encountered or studied."},
            },
            {
                "id": "cs_oop", "name": "Object-Oriented Programming",
                "xp_required": 300, "prerequisites": ["cs_python"],
                "xp_reward": 200, "difficulty": "Intermediate", "estimated_hours": 10,
                "description": "Classes, inheritance, polymorphism, design patterns.",
                "tasks": [
                    "Understand classes and objects",
                    "Write a class with __init__, attributes, and methods",
                    "Practice inheritance with a real example",
                    "Understand polymorphism and method overriding",
                    "Learn about encapsulation and private attributes",
                    "Study 2 common design patterns (e.g. Factory, Singleton)",
                    "Refactor an existing project to use OOP",
                    "Pass the OOP reflection checkpoint",
                ],
                "mastery_check": {"type": "reflection", "prompt": "Describe a real project or exercise where you used inheritance or polymorphism. What problem did it solve?"},
            },
            {
                "id": "cs_algorithms", "name": "Algorithms",
                "xp_required": 400, "prerequisites": ["cs_dsa"],
                "xp_reward": 300, "difficulty": "Advanced", "estimated_hours": 15,
                "description": "Sorting, searching, recursion, dynamic programming.",
                "tasks": [
                    "Understand Big O notation",
                    "Implement bubble sort and selection sort",
                    "Implement merge sort and understand divide & conquer",
                    "Implement binary search",
                    "Understand and write recursive functions",
                    "Solve 3 recursion problems (e.g. Fibonacci, factorial, tree traversal)",
                    "Learn dynamic programming (memoization vs tabulation)",
                    "Solve 2 DP problems (e.g. coin change, climbing stairs)",
                    "Pass the Algorithms challenge",
                ],
                "mastery_check": {"type": "challenge", "prompt": "Explain merge sort in your own words and describe why it's O(n log n). No need to write code — prove you understand it."},
            },
            {
                "id": "cs_web", "name": "Web Development",
                "xp_required": 350, "prerequisites": ["cs_oop"],
                "xp_reward": 250, "difficulty": "Intermediate", "estimated_hours": 20,
                "description": "APIs, HTTP, frontend basics, backend frameworks.",
                "tasks": [
                    "Understand how HTTP works (request/response, status codes)",
                    "Learn HTML and CSS basics",
                    "Build a static webpage",
                    "Learn JavaScript fundamentals",
                    "Consume a public REST API using fetch()",
                    "Build a simple backend with FastAPI or Flask",
                    "Connect frontend to backend API",
                    "Deploy a project to a hosting platform",
                    "Pass the Web Dev proof checkpoint",
                ],
                "mastery_check": {"type": "proof", "prompt": "Share a link to a project, GitHub repo, or describe in detail a web app you built. What does it do? What stack?"},
            },
            {
                "id": "cs_ai", "name": "AI & Machine Learning",
                "xp_required": 600, "prerequisites": ["cs_algorithms", "cs_oop"],
                "xp_reward": 400, "difficulty": "Advanced", "estimated_hours": 25,
                "description": "ML fundamentals, neural networks, model training.",
                "tasks": [
                    "Understand supervised vs unsupervised learning",
                    "Learn linear and logistic regression",
                    "Train a model with scikit-learn",
                    "Understand and handle overfitting (train/val/test split)",
                    "Learn neural network fundamentals",
                    "Build a neural network with PyTorch or Keras",
                    "Study a real ML paper or Kaggle notebook",
                    "Complete an end-to-end ML project",
                    "Pass the ML quiz",
                ],
                "mastery_check": {"type": "quiz", "prompt": "Explain overfitting: what causes it, how do you detect it, and two techniques to prevent it."},
            },
            {
                "id": "cs_security", "name": "Cybersecurity",
                "xp_required": 500, "prerequisites": ["cs_web", "cs_algorithms"],
                "xp_reward": 350, "difficulty": "Advanced", "estimated_hours": 18,
                "description": "Threats, encryption, auth, secure coding.",
                "tasks": [
                    "Understand the OWASP Top 10 vulnerabilities",
                    "Learn how SQL injection works and how to prevent it",
                    "Learn about XSS and CSRF attacks",
                    "Understand symmetric vs asymmetric encryption",
                    "Implement JWT-based authentication",
                    "Perform a security audit on one of your own projects",
                    "Study one real-world security breach case study",
                    "Pass the Cybersecurity challenge",
                ],
                "mastery_check": {"type": "challenge", "prompt": "Describe how SQL injection works and show (in pseudocode or plain English) how parameterized queries prevent it."},
            },
        ],
    },
    "Fitness": {
        "label": "Physical Mastery", "icon": "💪", "color": "#82b366",
        "nodes": [
            {
                "id": "fit_consistency", "name": "Consistency",
                "xp_required": 0, "prerequisites": [],
                "xp_reward": 100, "difficulty": "Beginner", "estimated_hours": 12,
                "description": "Exercise at least 3x/week for 4 consecutive weeks.",
                "tasks": [
                    "Schedule 3 workout days per week in your calendar",
                    "Complete week 1 (3 sessions)",
                    "Complete week 2 (3 sessions)",
                    "Complete week 3 (3 sessions)",
                    "Complete week 4 (3 sessions)",
                    "Log each session in your journal",
                    "Write a reflection: what made it easy or hard to stay consistent?",
                ],
                "mastery_check": {"type": "proof", "prompt": "Describe your current weekly exercise schedule. How many consecutive weeks have you maintained it? Be honest."},
            },
            {
                "id": "fit_strength", "name": "Strength Foundation",
                "xp_required": 100, "prerequisites": ["fit_consistency"],
                "xp_reward": 150, "difficulty": "Intermediate", "estimated_hours": 10,
                "description": "Master compound lifts: squat, deadlift, press.",
                "tasks": [
                    "Learn squat form (watch tutorial + practice with bodyweight)",
                    "Learn deadlift form (start with Romanian deadlift)",
                    "Learn overhead press form",
                    "Establish starting weights for all 3 lifts",
                    "Complete 4 strength sessions applying progressive overload",
                    "Track all weights in a log",
                    "Write a reflection on your current strengths and weaknesses",
                ],
                "mastery_check": {"type": "reflection", "prompt": "What are your current working weights for squat, deadlift, and press? What cues do you focus on for each?"},
            },
            {
                "id": "fit_cardio", "name": "Cardio Base",
                "xp_required": 100, "prerequisites": ["fit_consistency"],
                "xp_reward": 100, "difficulty": "Beginner", "estimated_hours": 6,
                "description": "Run 5km without stopping.",
                "tasks": [
                    "Run/walk 2km without stopping",
                    "Run/walk 3km without stopping",
                    "Complete 3 cardio sessions this week",
                    "Run 4km without stopping",
                    "Complete your first 5km without stopping",
                    "Log your 5km time",
                ],
                "mastery_check": {"type": "proof", "prompt": "Have you run 5km without stopping? Share your approximate time or describe the experience."},
            },
            {
                "id": "fit_nutrition", "name": "Nutrition Basics",
                "xp_required": 150, "prerequisites": ["fit_consistency"],
                "xp_reward": 125, "difficulty": "Beginner", "estimated_hours": 4,
                "description": "Track macros, meal prep, understand caloric balance.",
                "tasks": [
                    "Calculate your TDEE (Total Daily Energy Expenditure)",
                    "Learn the calorie counts for protein, fat, and carbs per gram",
                    "Track your food intake for 3 days using an app",
                    "Plan and prep one week of meals",
                    "Identify your top 3 nutrition habits to improve",
                    "Pass the Nutrition quiz",
                ],
                "mastery_check": {"type": "quiz", "prompt": "Explain what a caloric deficit is and roughly how many calories are in 1g of protein, fat, and carbs."},
            },
            {
                "id": "fit_advanced", "name": "Advanced Training",
                "xp_required": 400, "prerequisites": ["fit_strength", "fit_cardio"],
                "xp_reward": 300, "difficulty": "Advanced", "estimated_hours": 15,
                "description": "Periodization, progressive overload, recovery.",
                "tasks": [
                    "Understand periodization (linear, undulating, block)",
                    "Design a 4-week progressive overload plan for one lift",
                    "Learn about deload weeks",
                    "Study recovery: sleep, active rest, mobility",
                    "Implement the 4-week plan and track results",
                    "Adjust the plan based on performance",
                    "Write a reflection: what improved? What needs work?",
                ],
                "mastery_check": {"type": "challenge", "prompt": "Design a 4-week progressive overload plan for one compound lift. Show the week-by-week progression."},
            },
        ],
    },
    "Finance": {
        "label": "Financial Intelligence", "icon": "💰", "color": "#d6a73a",
        "nodes": [
            {
                "id": "fin_budgeting", "name": "Budgeting",
                "xp_required": 0, "prerequisites": [],
                "xp_reward": 100, "difficulty": "Beginner", "estimated_hours": 3,
                "description": "Track income and expenses, build a monthly budget.",
                "tasks": [
                    "List all your monthly income sources",
                    "List all your monthly fixed expenses",
                    "List all your monthly variable expenses",
                    "Categorize expenses (needs vs wants)",
                    "Build a monthly budget (use a spreadsheet or app)",
                    "Track actual vs planned spending for 2 weeks",
                    "Write a reflection: where does your money actually go?",
                ],
                "mastery_check": {"type": "reflection", "prompt": "What does your current monthly budget look like? What are your top 3 expense categories?"},
            },
            {
                "id": "fin_emergency", "name": "Emergency Fund",
                "xp_required": 100, "prerequisites": ["fin_budgeting"],
                "xp_reward": 125, "difficulty": "Beginner", "estimated_hours": 2,
                "description": "Save 3 months of expenses.",
                "tasks": [
                    "Calculate your monthly essential expenses",
                    "Calculate your 3-month emergency fund target",
                    "Open a separate savings account if you don't have one",
                    "Set up automatic monthly transfers to savings",
                    "Track your progress toward the target",
                    "Reach 1 month of savings",
                    "Reach 3 months of savings",
                ],
                "mastery_check": {"type": "proof", "prompt": "How many months of expenses do you currently have saved? What's your monthly expense baseline?"},
            },
            {
                "id": "fin_debt", "name": "Debt Elimination",
                "xp_required": 150, "prerequisites": ["fin_budgeting"],
                "xp_reward": 150, "difficulty": "Intermediate", "estimated_hours": 4,
                "description": "Avalanche or snowball method to eliminate debt.",
                "tasks": [
                    "List all your debts (balance, interest rate, minimum payment)",
                    "Learn the avalanche method",
                    "Learn the snowball method",
                    "Choose a method and write your payoff plan",
                    "Make one extra payment toward your highest-priority debt",
                    "Set a target debt-free date",
                ],
                "mastery_check": {"type": "quiz", "prompt": "Explain the difference between the avalanche and snowball debt repayment methods. Which would you choose and why?"},
            },
            {
                "id": "fin_investing", "name": "Investing Basics",
                "xp_required": 300, "prerequisites": ["fin_emergency"],
                "xp_reward": 250, "difficulty": "Intermediate", "estimated_hours": 8,
                "description": "Index funds, ETFs, compound interest, tax-advantaged accounts.",
                "tasks": [
                    "Understand compound interest with a concrete example",
                    "Learn the difference between stocks, bonds, and index funds",
                    "Learn what an ETF is",
                    "Research low-cost index fund options in your country",
                    "Open a brokerage or retirement account",
                    "Make your first investment (even a small one)",
                    "Set up recurring investment contributions",
                    "Pass the Investing challenge",
                ],
                "mastery_check": {"type": "challenge", "prompt": "Explain compound interest with a concrete example: what happens to ₱10,000 invested at 8% annually for 10 years?"},
            },
            {
                "id": "fin_income", "name": "Income Growth",
                "xp_required": 400, "prerequisites": ["fin_debt", "fin_investing"],
                "xp_reward": 300, "difficulty": "Advanced", "estimated_hours": 10,
                "description": "Side income, salary negotiation, skill monetization.",
                "tasks": [
                    "Identify 3 realistic income growth opportunities",
                    "Research market salaries for your role",
                    "Prepare a case for a salary negotiation or rate increase",
                    "Take one action toward a side income stream",
                    "Set a specific income goal with a deadline",
                    "Write a reflection: what skills of yours have the most market value?",
                ],
                "mastery_check": {"type": "reflection", "prompt": "What's one concrete step you've taken or plan to take to grow your income this year?"},
            },
        ],
    },
    "Creativity": {
        "label": "Creative Mastery", "icon": "🎨", "color": "#9c70c4",
        "nodes": [
            {
                "id": "cr_basics", "name": "Creative Foundations",
                "xp_required": 0, "prerequisites": [],
                "xp_reward": 100, "difficulty": "Beginner", "estimated_hours": 4,
                "description": "Daily practice habit, overcoming blank-page paralysis.",
                "tasks": [
                    "Choose your primary creative medium",
                    "Set a daily practice time (even 15 minutes counts)",
                    "Complete 5 consecutive days of creative practice",
                    "Make something bad on purpose (kill perfectionism)",
                    "Fill one page / screen / canvas with free experimentation",
                    "Write a reflection: what does your creative practice look like right now?",
                ],
                "mastery_check": {"type": "reflection", "prompt": "Describe your current creative practice. How often do you create? What do you make?"},
            },
            {
                "id": "cr_craft", "name": "Craft Fundamentals",
                "xp_required": 100, "prerequisites": ["cr_basics"],
                "xp_reward": 150, "difficulty": "Intermediate", "estimated_hours": 10,
                "description": "Core techniques for your chosen medium.",
                "tasks": [
                    "Identify 3 core techniques essential to your medium",
                    "Study and practice technique 1 with focused repetition",
                    "Study and practice technique 2 with focused repetition",
                    "Study and practice technique 3 with focused repetition",
                    "Analyze a master work in your medium and identify the techniques used",
                    "Create one piece that deliberately applies all 3 techniques",
                    "Pass the Craft proof checkpoint",
                ],
                "mastery_check": {"type": "proof", "prompt": "Share or describe a piece of work that demonstrates a core technique in your medium. What technique does it show?"},
            },
            {
                "id": "cr_voice", "name": "Personal Voice",
                "xp_required": 250, "prerequisites": ["cr_craft"],
                "xp_reward": 200, "difficulty": "Intermediate", "estimated_hours": 8,
                "description": "Develop a distinct style others can recognise.",
                "tasks": [
                    "List 5 creators whose work resonates with you and why",
                    "Identify the patterns in what you're drawn to",
                    "Create 3 pieces exploring a consistent theme or aesthetic",
                    "Share your work with someone and ask what word comes to mind",
                    "Describe your style in 3 words and write about what shapes it",
                ],
                "mastery_check": {"type": "reflection", "prompt": "How would you describe your creative style in 3 words? What influences it most?"},
            },
            {
                "id": "cr_project", "name": "Finish a Project",
                "xp_required": 200, "prerequisites": ["cr_craft"],
                "xp_reward": 175, "difficulty": "Intermediate", "estimated_hours": 15,
                "description": "Complete one significant creative work end-to-end.",
                "tasks": [
                    "Define the scope of one significant creative project",
                    "Create an outline or plan for the project",
                    "Complete 25% of the project",
                    "Complete 50% of the project",
                    "Complete 75% of the project",
                    "Complete and finalize the project",
                    "Write a reflection: what was hardest about finishing?",
                ],
                "mastery_check": {"type": "proof", "prompt": "Describe a complete creative project you've finished recently. What was the hardest part of finishing it?"},
            },
            {
                "id": "cr_share", "name": "Share Your Work",
                "xp_required": 350, "prerequisites": ["cr_voice", "cr_project"],
                "xp_reward": 250, "difficulty": "Advanced", "estimated_hours": 5,
                "description": "Publish, perform, or exhibit. Feedback loop matters.",
                "tasks": [
                    "Choose a platform or venue to share your work",
                    "Prepare one piece for public sharing",
                    "Share your work publicly",
                    "Collect at least 3 pieces of feedback",
                    "Write a reflection: how did sharing feel? What did you learn?",
                ],
                "mastery_check": {"type": "proof", "prompt": "Where did you share your work? What was the response? (A link, a description of a performance, or a screenshot description works.)"},
            },
        ],
    },
    "Personal Growth": {
        "label": "Self Mastery", "icon": "🌱", "color": "#d07040",
        "nodes": [
            {
                "id": "pg_awareness", "name": "Self Awareness",
                "xp_required": 0, "prerequisites": [],
                "xp_reward": 100, "difficulty": "Beginner", "estimated_hours": 3,
                "description": "Daily journaling, identify core values and blind spots.",
                "tasks": [
                    "Journal every day for 7 days",
                    "Write down your top 5 core values",
                    "Identify one significant blind spot through journaling",
                    "Ask someone you trust for one honest piece of feedback",
                    "Write a reflection: who are you, really?",
                ],
                "mastery_check": {"type": "reflection", "prompt": "Name 3 of your core values and one blind spot you've identified through journaling. Be specific."},
            },
            {
                "id": "pg_habits", "name": "Habit Architecture",
                "xp_required": 100, "prerequisites": ["pg_awareness"],
                "xp_reward": 150, "difficulty": "Intermediate", "estimated_hours": 6,
                "description": "Design habit stacks, track streaks, remove friction.",
                "tasks": [
                    "Read about habit loops (cue, routine, reward)",
                    "Identify one habit you want to build",
                    "Define the cue, routine, and reward for that habit",
                    "Remove 3 sources of friction for that habit",
                    "Complete the habit for 14 consecutive days",
                    "Design a habit stack (attach new habit to an existing one)",
                    "Write a reflection: describe exactly how you built this habit",
                ],
                "mastery_check": {"type": "challenge", "prompt": "Describe one habit you've built successfully. What cue triggers it, what's the routine, and what's the reward?"},
            },
            {
                "id": "pg_mindset", "name": "Growth Mindset",
                "xp_required": 150, "prerequisites": ["pg_awareness"],
                "xp_reward": 125, "difficulty": "Beginner", "estimated_hours": 4,
                "description": "Reframe failure, embrace discomfort, learn from feedback.",
                "tasks": [
                    "Study the concept of fixed vs growth mindset",
                    "Identify one area where you have a fixed mindset",
                    "Take on one challenge that is slightly beyond your comfort zone",
                    "Write about a recent failure: what did it teach you?",
                    "Actively seek critical feedback on something you made",
                    "Write a reflection: how do you respond to failure now vs before?",
                ],
                "mastery_check": {"type": "reflection", "prompt": "Describe a recent failure or setback. How did you respond to it? What did you learn?"},
            },
            {
                "id": "pg_focus", "name": "Deep Focus",
                "xp_required": 200, "prerequisites": ["pg_habits"],
                "xp_reward": 200, "difficulty": "Intermediate", "estimated_hours": 8,
                "description": "Deep work sessions, distraction elimination, flow state.",
                "tasks": [
                    "Audit your current distractions (phone, notifications, environment)",
                    "Remove or silence your top 3 distractions",
                    "Complete a 45-minute deep work session without interruption",
                    "Complete a 90-minute deep work session",
                    "Build a consistent deep work routine (same time, same place)",
                    "Complete 10 deep work sessions total",
                    "Write a reflection: describe your best focus session this week",
                ],
                "mastery_check": {"type": "challenge", "prompt": "Describe your current deep work setup. How long can you focus without distraction? What's your best session length this week?"},
            },
            {
                "id": "pg_leadership", "name": "Leadership",
                "xp_required": 500, "prerequisites": ["pg_mindset", "pg_focus"],
                "xp_reward": 350, "difficulty": "Advanced", "estimated_hours": 12,
                "description": "Influence, communication, accountability to others.",
                "tasks": [
                    "Read one book or resource on leadership or communication",
                    "Identify one person you can mentor, support, or lead",
                    "Have one honest accountability conversation with someone",
                    "Lead or initiate one group project or initiative",
                    "Practice public speaking or presenting (even to a small group)",
                    "Write a reflection: describe a moment you influenced someone positively",
                ],
                "mastery_check": {"type": "reflection", "prompt": "Describe a situation where you led, influenced, or held someone (including yourself) accountable. What was the outcome?"},
            },
        ],
    },
}

def get_completed_node_ids(category: str) -> set[str]:
    result = (
        supabase.table("skill_progress")
        .select("node_id").eq("category", category).execute()
    )
    return {row["node_id"] for row in result.data}

def _get_active_skill_goals(category: str) -> dict:
    """Returns {node_id: {goal_id, completed_tasks, total_tasks, progress}} for active skill goals."""
    try:
        goals = supabase.table("goals").select("id, tags").eq("category", category).execute()
        tasks = supabase.table("goal_tasks").select("goal_id, is_completed").execute()
        tasks_by_goal = defaultdict(list)
        for t in tasks.data:
            tasks_by_goal[t["goal_id"]].append(t["is_completed"])
        result = {}
        for g in goals.data:
            nid = node_id_from_tags(g.get("tags") or [])
            if nid:
                tlist = tasks_by_goal.get(g["id"], [])
                done  = sum(1 for x in tlist if x)
                total = len(tlist)
                result[nid] = {
                    "goal_id":         g["id"],
                    "completed_tasks":  done,
                    "total_tasks":      total,
                    "progress":         round(done / total * 100) if total else 0,
                }
        return result
    except Exception:
        return {}

def resolve_tree(category: str) -> dict:
    tree_def = SKILL_TREES.get(category)
    if not tree_def:
        return {}
    xp            = get_category_xp(category)
    completed_ids = get_completed_node_ids(category)
    active_goals  = _get_active_skill_goals(category)
    resolved      = []
    for node in tree_def["nodes"]:
        prereqs_met = all(p in completed_ids for p in node["prerequisites"])
        xp_met      = xp >= node["xp_required"]
        unlocked    = prereqs_met and xp_met
        completed   = node["id"] in completed_ids
        active      = active_goals.get(node["id"])
        resolved.append({
            **node,
            "unlocked":    unlocked,
            "completed":   completed,
            "prereqs_met": prereqs_met,
            "xp_met":      xp_met,
            "category_xp": xp,
            "active_goal": active,   # None or {goal_id, completed_tasks, total_tasks, progress}
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
# Skill-Driven Quest System — Start Learning
# ---------------------------------------------------------------------------

@app.post("/skills/{node_id}/start")
def start_learning(node_id: str, category: str):
    """
    Creates a Goal + Tasks from a skill node template.
    Idempotent: if a goal already exists for this node, returns it.
    """
    tree = resolve_tree(category)
    if not tree:
        raise HTTPException(404, "Tree not found")
    node = next((n for n in tree["nodes"] if n["id"] == node_id), None)
    if not node:
        raise HTTPException(404, "Node not found")
    if not node["unlocked"]:
        raise HTTPException(403, "Node is locked. Complete prerequisites first.")
    if node["completed"]:
        raise HTTPException(400, "Node already completed.")

    # Idempotency: return existing active goal if already started
    if node.get("active_goal"):
        ag = node["active_goal"]
        return {
            "status":  "already_active",
            "goal_id": ag["goal_id"],
            "message": f"You already have an active learning goal for {node['name']}.",
        }

    # Create the goal, tagged with the skill node id
    goal_result = supabase.table("goals").insert({
        "title":        f"Learn {node['name']}",
        "category":     category,
        "is_completed":  False,
        "tags":         [tag_for_node(node_id)],
        "created_at":   datetime.now(timezone.utc).isoformat(),
    }).execute()
    goal_id = goal_result.data[0]["id"]

    # Create tasks from the node blueprint
    task_rows = [
        {
            "goal_id":      goal_id,
            "title":        task_title,
            "is_completed": False,
            "created_at":   datetime.now(timezone.utc).isoformat(),
        }
        for task_title in node.get("tasks", [])
    ]
    if task_rows:
        supabase.table("goal_tasks").insert(task_rows).execute()

    return {
        "status":   "started",
        "goal_id":  goal_id,
        "node_id":  node_id,
        "category": category,
        "goal_title": f"Learn {node['name']}",
        "task_count": len(task_rows),
        "xp_reward":  node.get("xp_reward", 100),
    }

def _auto_complete_skill_node_if_done(goal_id: int):
    """
    Called after every task toggle.
    If all tasks in a skill-linked goal are complete, automatically
    completes the skill node (bypassing mastery check — tasks ARE the proof).
    """
    try:
        goal = supabase.table("goals").select("*").eq("id", goal_id).single().execute()
        if not goal.data:
            return None
        node_id = node_id_from_tags(goal.data.get("tags") or [])
        if not node_id:
            return None  # Not a skill-linked goal

        tasks = supabase.table("goal_tasks").select("is_completed").eq("goal_id", goal_id).execute()
        if not tasks.data:
            return None
        if not all(t["is_completed"] for t in tasks.data):
            return None  # Not all done yet

        category = goal.data["category"]
        tree = resolve_tree(category)
        node = next((n for n in tree["nodes"] if n["id"] == node_id), None)
        if not node or node["completed"]:
            return None  # Already done

        # Mark node completed
        supabase.table("skill_progress").upsert({
            "node_id":      node_id,
            "category":     category,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }).execute()

        xp_bonus = node.get("xp_reward", node["xp_required"] // 2 + 50)
        ledger_add("skill_node", node_id, category, xp_bonus)
        new_achievements = award_achievements()

        updated_tree = resolve_tree(category)
        newly_unlocked = [
            n["name"] for n in updated_tree["nodes"]
            if n["unlocked"] and not n["completed"] and n["id"] != node_id
        ]

        return {
            "skill_completed": True,
            "node_id":         node_id,
            "node_name":       node["name"],
            "category":        category,
            "xp_earned":       xp_bonus,
            "new_achievements": new_achievements,
            "newly_unlocked":  newly_unlocked,
        }
    except Exception:
        return None

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
        alerts.append("Mood and energy both flat for 7+ entries")

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
        .select("id, mood, energy, focus, entry_type, created_at")
        .order("created_at").execute()
    )
    return [
        {
            "id": e["id"],
            "mood": safe_rating(e.get("mood")),
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
        .select("id, title, content, mood, energy, focus, entry_type, tags, created_at")
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
            f"Focus: {e.get('focus',3)}/5){tags} "
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
    weekly = defaultdict(lambda: {"moods": [], "count": 0})
    for e in older:
        dt = datetime.fromisoformat(e["created_at"].replace("Z", "+00:00"))
        year, week, _ = dt.isocalendar()
        key = f"{year}-W{week:02d}"
        weekly[key]["moods"].append(e["mood"])
        weekly[key]["count"] += 1
    rows = [
        f"{k}: avg mood {round(sum(v['moods'])/len(v['moods']),1)}/5, {v['count']} entries"
        for k in sorted(weekly.keys())
    ]
    if len(rows) > MAX_WEEKLY_ROWS:
        h, t = rows[:MAX_WEEKLY_ROWS//2], rows[-(MAX_WEEKLY_ROWS//2):]
        rows = h + [f"... ({len(rows)-len(h)-len(t)} weeks omitted) ..."] + t
    return "\n".join(rows)

def build_trend_stats_block(all_light_entries: list[dict]) -> str:
    if not all_light_entries:
        return "No data yet."
    moods    = [e["mood"]   for e in all_light_entries]
    energies = [e["energy"] for e in all_light_entries]
    focuses  = [e["focus"]  for e in all_light_entries]
    r7, p7 = all_light_entries[-7:], all_light_entries[-14:-7] if len(all_light_entries) >= 14 else []
    lines = [
        f"Overall mood trend: {describe_trend(linear_slope(moods))} over {len(moods)} entries.",
        f"Overall energy trend: {describe_trend(linear_slope(energies))} over {len(energies)} entries.",
        f"Overall focus trend: {describe_trend(linear_slope(focuses))} over {len(focuses)} entries.",
    ]
    if p7:
        lines.append(
            f"Last 7 avg: mood {avg([e['mood'] for e in r7])}/5, "
            f"energy {avg([e['energy'] for e in r7])}/5, "
            f"focus {avg([e['focus'] for e in r7])}/5. "
            f"Prev 7 avg: mood {avg([e['mood'] for e in p7])}/5, "
            f"energy {avg([e['energy'] for e in p7])}/5, "
            f"focus {avg([e['focus'] for e in p7])}/5."
        )
    return "\n".join(lines)

def build_habit_block() -> str:
    result = supabase.table("habits").select("name, completed_at").order("completed_at", desc=True).execute()
    habit_dates: dict[str, list] = defaultdict(list)
    for row in result.data:
        habit_dates[row["name"]].append(row["completed_at"])
    habit_meta = _fetch_habit_meta()
    if not habit_dates:
        return "No habits tracked yet."
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return "\n".join(
        f"- {name} [{habit_meta.get(name,{}).get('category','?')}]: {calc_streak(sorted(set(dates), reverse=True), today)}-day streak, "
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
        f"[{e['created_at'][:10]}] (Mood: {e['mood']}/5) "
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
    moods    = [e["mood"]   for e in all_light]
    energies = [e["energy"] for e in all_light]
    focuses  = [e["focus"]  for e in all_light]
    m_slope  = linear_slope(moods)
    e_slope  = linear_slope(energies)
    f_slope  = linear_slope(focuses)
    if m_slope > 0.05:
        insights.append({"type": "success", "title": "Mood Trend",
            "message": "Your mood has been improving over time.",
            "recommendation": "Review recent entries to identify what's helping."})
    elif m_slope < -0.05:
        insights.append({"type": "warning", "title": "Mood Trend",
            "message": "Your mood has been gradually declining.",
            "recommendation": "Look for recurring stressors in your last few entries."})
    if e_slope > 0.05:
        insights.append({"type": "success", "title": "Energy Trend",
            "message": "Your energy levels are trending upward.",
            "recommendation": "Keep up the habits that are sustaining this."})
    elif e_slope < -0.05:
        insights.append({"type": "warning", "title": "Energy Trend",
            "message": "Your energy has been declining.",
            "recommendation": "Check your sleep, movement, and workload this week."})
    if f_slope > 0.05:
        insights.append({"type": "success", "title": "Focus Trend",
            "message": "Your focus is on the rise.",
            "recommendation": "Note what environment and routines are helping."})
    elif f_slope < -0.05:
        insights.append({"type": "warning", "title": "Focus Trend",
            "message": "Your focus has been slipping.",
            "recommendation": "Try a distraction audit — what's competing for your attention?"})
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
            "message": "Mood and energy have both been flat for 7+ entries.",
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
    moods     = [e["mood"]   for e in all_light]
    energies  = [e["energy"] for e in all_light]
    focuses   = [e["focus"]  for e in all_light]
    corr      = get_correlations()
    valid     = [d for d in corr if d["avg_mood"] > 0]
    best_day  = max(valid, key=lambda d: d["avg_mood"]) if valid else None
    streaks   = _compute_streaks_raw()
    best_h    = max(streaks.items(), key=lambda x: x[1]["current_streak"]) if streaks else (None, {"current_streak": 0})
    analytics = predictive_analytics()
    total_xp  = get_total_xp()
    return {
        "entries":          len(all_light),
        "avg_mood":         round(sum(moods)    / len(moods),    1),
        "avg_energy":       round(sum(energies) / len(energies), 1),
        "avg_focus":        round(sum(focuses)  / len(focuses),  1),
        "mood_trend":       describe_trend(linear_slope(moods)),
        "energy_trend":     describe_trend(linear_slope(energies)),
        "focus_trend":      describe_trend(linear_slope(focuses)),
        "best_day":         best_day["day"] if best_day else None,
        "best_day_mood":    best_day["avg_mood"] if best_day else None,
        "strongest_habit":  best_h[0],
        "habit_streak":     best_h[1]["current_streak"],
        "total_xp":         total_xp,
        "level":            xp_to_level(total_xp)["level"],
        "streak_at_risk":   analytics["streak_at_risk"],
        "stagnating":       analytics["stagnating"],
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
        .select("title, content, mood, energy, focus, created_at")
        .gte("created_at", start.isoformat()).order("created_at").execute()
    ).data

@app.get("/monthly-review")
def monthly_review():
    entries = get_current_month_entries()
    if not entries:
        return {"review": "Not enough journal entries this month yet."}
    moods    = [e["mood"]   for e in entries]
    energies = [e.get("energy", 3) for e in entries]
    focuses  = [e.get("focus",  3) for e in entries]
    corr     = get_correlations()
    valid    = [d for d in corr if d["avg_mood"] > 0]
    best_day = max(valid, key=lambda d: d["avg_mood"])["day"] if valid else None
    streaks  = _compute_streaks_raw()
    best_h   = max(streaks.items(), key=lambda x: x[1]["current_streak"])[0] if streaks else None
    goal_data  = build_goal_summary()
    cat_health = build_category_health(goal_data)
    total_xp   = sum(g["xp"] for g in goal_data)
    completed_q = sum(g["completed_tasks"] for g in goal_data)
    total_q     = sum(g["total_tasks"]    for g in goal_data)
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
        "entry_count":   len(entries),
        "avg_mood":      round(sum(moods)    / len(moods),    1),
        "avg_energy":    round(sum(energies) / len(energies), 1),
        "avg_focus":     round(sum(focuses)  / len(focuses),  1),
        "mood_trend":    describe_trend(linear_slope(moods)),
        "energy_trend":  describe_trend(linear_slope(energies)),
        "focus_trend":   describe_trend(linear_slope(focuses)),
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
# Life Domains — aggregate XP/goals/habits/skills per domain
# ---------------------------------------------------------------------------

# Mapping: domain name → categories/skill-tree keys that contribute to it
DOMAIN_DEFINITIONS = {
    "Computer Science": {
        "icon": "💻", "color": "#6c8ebf",
        "skill_keys":   ["Study"],
        "goal_cats":    ["Study", "Computer Science"],
        "habit_cats":   ["Learning", "Productivity"],
        "description":  "Programming, algorithms, systems thinking.",
    },
    "Health": {
        "icon": "💪", "color": "#82b366",
        "skill_keys":   ["Fitness"],
        "goal_cats":    ["Fitness", "Health", "Wellness"],
        "habit_cats":   ["Physical", "Mind"],
        "description":  "Physical fitness, sleep, nutrition, mental health.",
    },
    "Music": {
        "icon": "🎵", "color": "#9c70c4",
        "skill_keys":   ["Creativity"],
        "goal_cats":    ["Music", "Creativity"],
        "habit_cats":   ["Creativity"],
        "description":  "Instruments, composition, ear training.",
    },
    "Relationships": {
        "icon": "❤️", "color": "#d98aa0",
        "skill_keys":   ["Personal Growth"],
        "goal_cats":    ["Relationship", "Social", "Relationships"],
        "habit_cats":   ["Social"],
        "description":  "Friendships, family, communication, empathy.",
    },
    "Personal Growth": {
        "icon": "🌱", "color": "#d07040",
        "skill_keys":   ["Personal Growth"],
        "goal_cats":    ["Personal Growth", "Mindset"],
        "habit_cats":   ["Mind", "Productivity"],
        "description":  "Habits, mindset, leadership, self-awareness.",
    },
    "Finance": {
        "icon": "💰", "color": "#d6a73a",
        "skill_keys":   ["Finance"],
        "goal_cats":    ["Finance", "Career"],
        "habit_cats":   ["Productivity"],
        "description":  "Budgeting, investing, income growth.",
    },
    "Creativity": {
        "icon": "🎨", "color": "#b8617c",
        "skill_keys":   ["Creativity"],
        "goal_cats":    ["Creativity", "Art", "Writing"],
        "habit_cats":   ["Creativity"],
        "description":  "Art, writing, design, creative expression.",
    },
}

def build_domain(name: str, defn: dict) -> dict:
    """Build full domain snapshot by aggregating from all sub-systems."""
    # XP: sum ledger for all skill_keys + goal_cats
    xp = 0
    all_cats = set(defn["skill_keys"] + defn["goal_cats"])
    for cat in all_cats:
        xp += get_category_xp(cat)

    level_info = xp_to_level(xp)

    # Goals in domain
    all_goals = build_goal_summary()
    domain_goals = [
        g for g in all_goals
        if g.get("category") in set(defn["goal_cats"])
    ]
    total_tasks     = sum(g["total_tasks"] for g in domain_goals)
    completed_tasks = sum(g["completed_tasks"] for g in domain_goals)
    progress        = round(completed_tasks / total_tasks * 100) if total_tasks > 0 else 0

    # Habits in domain — look up domain via habit_profiles instead of category column
    try:
        habit_result = supabase.table("habits").select("name, completed_at").execute()
        profiles_res = supabase.table("habit_profiles").select("name, domain").execute()
        profile_map  = {r["name"]: r.get("domain", "Personal Growth") for r in profiles_res.data}
        today        = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        domain_habits: dict[str, dict] = {}
        for row in habit_result.data:
            habit_domain = profile_map.get(row["name"], "Personal Growth")
            if habit_domain == name:  # match by domain name directly
                n = row["name"]
                if n not in domain_habits:
                    domain_habits[n] = {"dates": []}
                domain_habits[n]["dates"].append(row["completed_at"])
        habit_summary = []
        for hname, hdata in domain_habits.items():
            unique = sorted(set(hdata["dates"]), reverse=True)
            habit_summary.append({
                "name":           hname,
                "streak":         calc_streak(unique, today),
                "total":          len(unique),
                "done_today":     today in unique,
            })
    except Exception:
        habit_summary = []

    # Skill tree nodes
    skill_stats = []
    for sk in defn["skill_keys"]:
        tree = resolve_tree(sk)
        if tree and tree.get("nodes"):
            nodes     = tree["nodes"]
            completed = sum(1 for n in nodes if n["completed"])
            total     = len(nodes)
            skill_stats.append({
                "tree":      sk,
                "label":     tree.get("label", sk),
                "completed": completed,
                "total":     total,
                "pct":       round(completed / total * 100) if total else 0,
            })

    # Achievements earned in domain categories
    try:
        ach_rows = supabase.table("achievements").select("name, earned_at").execute().data
        # Use XP ledger to approximate domain achievements (by source_type=achievement)
        domain_ach_count = len(ach_rows)  # simplified — all achievements count
    except Exception:
        domain_ach_count = 0

    # Boss battle this week
    boss = _get_current_boss_for_domain(name)

    return {
        "name":          name,
        "icon":          defn["icon"],
        "color":         defn["color"],
        "description":   defn["description"],
        "xp":            xp,
        "level":         level_info["level"],
        "xp_in_level":   level_info["xp_in_level"],
        "xp_to_next":    level_info["xp_to_next"],
        "progress":      progress,
        "goals":         domain_goals,
        "active_goals":  len([g for g in domain_goals if g["progress"] < 100]),
        "habits":        habit_summary,
        "skill_trees":   skill_stats,
        "weekly_boss":   boss,
    }

def _get_current_boss_for_domain(domain: str) -> Optional[dict]:
    """Return the current week's boss for a domain, if any."""
    try:
        now      = datetime.now(timezone.utc)
        year, week, _ = now.isocalendar()
        week_key = f"{year}-W{week:02d}"
        result   = (
            supabase.table("weekly_bosses")
            .select("*")
            .eq("week_key", week_key)
            .eq("domain", domain)
            .execute()
        )
        if not result.data:
            return None
        boss = result.data[0]
        # Check if completed
        completed = (
            supabase.table("boss_completions")
            .select("id")
            .eq("boss_id", boss["id"])
            .execute()
        )
        boss["completed"] = len(completed.data) > 0
        boss["requirements"] = boss.get("requirements") or []
        return boss
    except Exception:
        return None

@app.get("/domains")
def get_domains():
    """Return all life domains with aggregated stats."""
    return [build_domain(name, defn) for name, defn in DOMAIN_DEFINITIONS.items()]

@app.get("/domains/{domain_name}")
def get_domain(domain_name: str):
    defn = DOMAIN_DEFINITIONS.get(domain_name)
    if not defn:
        raise HTTPException(404, "Domain not found")
    return build_domain(domain_name, defn)

# ---------------------------------------------------------------------------
# Weekly Boss Battles
# ---------------------------------------------------------------------------

class BossCompleteRequest(BaseModel):
    boss_id: int

@app.post("/bosses/generate")
def generate_weekly_boss():
    """AI generates a boss battle for the current week across all domains."""
    now          = datetime.now(timezone.utc)
    year, week, _ = now.isocalendar()
    week_key     = f"{year}-W{week:02d}"
    deadline     = (now + timedelta(days=(6 - now.weekday()))).strftime("%Y-%m-%d")

    # Check if already generated this week
    existing = supabase.table("weekly_bosses").select("*").eq("week_key", week_key).execute()
    if existing.data:
        return {"bosses": existing.data, "week_key": week_key, "status": "existing"}

    # Gather context for AI
    goal_data  = build_goal_summary()
    streaks    = _compute_streaks_raw()
    analytics  = predictive_analytics()

    active_skill_cats = []
    for cat in SKILL_TREES:
        tree = resolve_tree(cat)
        if tree and any(n["unlocked"] and not n["completed"] for n in tree["nodes"]):
            active_skill_cats.append(cat)

    pending_goals = [
        {"title": g["title"], "category": g["category"], "progress": g["progress"]}
        for g in goal_data if g["progress"] < 100
    ][:6]

    top_habits = sorted(streaks.items(), key=lambda x: x[1]["current_streak"], reverse=True)[:4]
    habit_context = [{"name": n, "streak": d["current_streak"], "category": d["category"]} for n, d in top_habits]

    prompt = f"""You are LiAInne generating weekly boss battles for a personal growth RPG.

Current week: {week_key}
Active goals: {_json.dumps(pending_goals)}
Top habits: {_json.dumps(habit_context)}
Active skill trees: {active_skill_cats}
Stagnating: {analytics.get('stagnating', False)}
Streak risks: {analytics.get('streak_at_risk', [])}

Generate exactly 3 boss battles for different life domains from: {list(DOMAIN_DEFINITIONS.keys())}

Each boss should:
- Be achievable in one week
- Require 3-5 specific actions
- Feel epic but realistic
- Connect to the user's actual active goals/habits

Reply ONLY in this JSON (no markdown):
[
  {{
    "name": "Boss name (dramatic, like 'The Algorithm Gauntlet')",
    "description": "2 sentences of epic flavor text",
    "domain": "exact domain name from the list",
    "requirements": [
      {{"label": "action description", "target": 1, "type": "count"}}
    ],
    "xp_reward": 150
  }}
]

Max 3 bosses. Make them distinct domains."""

    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.85, max_tokens=600,
    )
    raw = response.choices[0].message.content.strip()
    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = "\n".join(raw.split("\n")[1:])
    if raw.endswith("```"):
        raw = "\n".join(raw.split("\n")[:-1])
    try:
        bosses_raw = _json.loads(raw.strip())
    except _json.JSONDecodeError:
        raise HTTPException(500, "Boss generation failed")

    created = []
    for b in bosses_raw[:3]:
        domain = b.get("domain", "Personal Growth")
        if domain not in DOMAIN_DEFINITIONS:
            domain = "Personal Growth"
        result = supabase.table("weekly_bosses").insert({
            "week_key":     week_key,
            "name":         b.get("name", "Weekly Boss"),
            "description":  b.get("description", ""),
            "domain":       domain,
            "requirements": _json.dumps(b.get("requirements", [])),
            "xp_reward":    min(max(int(b.get("xp_reward", 150)), 100), 400),
            "deadline":     deadline,
        }).execute()
        if result.data:
            created.append(result.data[0])

    return {"bosses": created, "week_key": week_key, "status": "created"}

@app.get("/bosses/current")
def get_current_bosses():
    """Get this week's boss battles with completion status."""
    now          = datetime.now(timezone.utc)
    year, week, _ = now.isocalendar()
    week_key     = f"{year}-W{week:02d}"
    result       = supabase.table("weekly_bosses").select("*").eq("week_key", week_key).execute()
    bosses       = []
    for boss in result.data:
        completed = supabase.table("boss_completions").select("id").eq("boss_id", boss["id"]).execute()
        req = boss.get("requirements")
        if isinstance(req, str):
            try:    req = _json.loads(req)
            except: req = []
        bosses.append({
            **boss,
            "requirements": req or [],
            "completed":    len(completed.data) > 0,
        })
    return {"bosses": bosses, "week_key": week_key}

@app.post("/bosses/{boss_id}/complete")
def complete_boss(boss_id: int):
    """Mark a boss battle as defeated."""
    boss = supabase.table("weekly_bosses").select("*").eq("id", boss_id).execute()
    if not boss.data:
        raise HTTPException(404, "Boss not found")
    # Idempotent
    existing = supabase.table("boss_completions").select("id").eq("boss_id", boss_id).execute()
    if existing.data:
        return {"status": "already_completed"}
    b        = boss.data[0]
    xp       = b.get("xp_reward", 200)
    domain   = b.get("domain", "Personal Growth")
    # Map domain → ledger category
    skill_keys = DOMAIN_DEFINITIONS.get(domain, {}).get("skill_keys", ["Personal Growth"])
    ledger_cat = skill_keys[0] if skill_keys else "Personal Growth"
    supabase.table("boss_completions").insert({
        "boss_id":      boss_id,
        "xp_earned":    xp,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }).execute()
    ledger_add("boss", str(boss_id), ledger_cat, xp)
    new_achievements = award_achievements()
    return {
        "status":          "defeated",
        "xp_earned":       xp,
        "domain":          domain,
        "new_achievements": new_achievements,
    }

# ---------------------------------------------------------------------------
# Proactive GET /action-engine (structured recommendations, no journal entry required)
# ---------------------------------------------------------------------------

@app.get("/action-engine")
def get_action_engine():
    """
    Proactive structured recommendations — runs without needing a journal entry.
    Detects stagnation, burnout risk, broken streaks, skill bottlenecks, goal failure.
    Returns problem + evidence + recommended action + suggested quest/habit/node.
    """
    analytics  = predictive_analytics()
    all_light  = fetch_all_entries_light()
    goal_data  = build_goal_summary()
    streaks    = _compute_streaks_raw()
    cat_health = build_category_health(goal_data)

    problems = []

    # 1. Stagnation
    if analytics.get("stagnating"):
        problems.append({
            "type":     "stagnation",
            "severity": "high",
            "title":    "Growth Plateau Detected",
            "evidence": ["Mood flat for 7+ entries", "Energy flat for 7+ entries"],
            "action":   "Pick one hard task you've been avoiding and spend 30 minutes on it today.",
        })

    # 2. Burnout risk: energy slope declining
    if len(all_light) >= 5:
        energies = [e["energy"] for e in all_light[-7:]]
        e_slope  = linear_slope(energies)
        if e_slope < -0.15:
            problems.append({
                "type":     "burnout_risk",
                "severity": "medium",
                "title":    "Energy Declining — Burnout Risk",
                "evidence": [f"Energy trending down over last {len(energies)} entries",
                             f"Average energy: {round(sum(energies)/len(energies),1)}/5"],
                "action":   "Take one rest day. Reduce active goals to 2 max this week.",
            })

    # 3. Broken streaks
    if analytics.get("streak_at_risk"):
        at_risk = analytics["streak_at_risk"]
        problems.append({
            "type":     "broken_streak",
            "severity": "high",
            "title":    f"Streak at Risk: {', '.join(at_risk)}",
            "evidence": [f"Logged {h} yesterday but not today" for h in at_risk[:3]],
            "action":   f"Log '{at_risk[0]}' right now. It takes 2 minutes.",
            "suggested_habit": at_risk[0],
        })

    # 4. Goal failure risk
    if analytics.get("goal_failure_risk"):
        risky = analytics["goal_failure_risk"][:2]
        problems.append({
            "type":     "goal_failure",
            "severity": "medium",
            "title":    "Goals Drifting Toward Failure",
            "evidence": [f"'{g['title']}' — {g['progress']}% after {g['days']} days" for g in risky],
            "action":   f"Open '{risky[0]['title']}' and complete one task right now.",
            "suggested_quest": risky[0]["title"],
        })

    # 5. Skill bottleneck: unlocked node with no active goal
    bottleneck_node = None
    for cat, tree_def in SKILL_TREES.items():
        tree = resolve_tree(cat)
        if not tree:
            continue
        for node in tree["nodes"]:
            if node["unlocked"] and not node["completed"] and not node.get("active_goal"):
                bottleneck_node = {"node": node["name"], "category": cat}
                break
        if bottleneck_node:
            break
    if bottleneck_node:
        problems.append({
            "type":     "skill_bottleneck",
            "severity": "low",
            "title":    "Skill Node Available but Untouched",
            "evidence": [f"'{bottleneck_node['node']}' in {bottleneck_node['category']} is unlocked but not started"],
            "action":   f"Start the '{bottleneck_node['node']}' learning path to keep progressing.",
            "suggested_skill_node": bottleneck_node,
        })

    # 6. Declining consistency
    if analytics.get("declining_consistency"):
        score = analytics["consistency_score"]
        problems.append({
            "type":     "declining_consistency",
            "severity": "medium",
            "title":    "Journal Consistency Dropping",
            "evidence": [f"Only {score}% journaling rate in past 2 weeks",
                         f"Missed {analytics['missed_days_count']} days"],
            "action":   "Write a 2-sentence journal entry right now. It resets the pattern.",
        })

    # If nothing bad, return a positive nudge
    if not problems:
        total_xp = get_total_xp()
        li       = xp_to_level(total_xp)
        return {
            "needs_attention": False,
            "problems":        [],
            "summary":         f"Everything looks good. You're Level {li['level']} with {total_xp} XP. Keep it up.",
        }

    # Sort by severity
    sev_order = {"high": 0, "medium": 1, "low": 2}
    problems.sort(key=lambda p: sev_order.get(p["severity"], 3))

    return {
        "needs_attention": True,
        "problems":        problems,
        "primary":         problems[0],
        "summary":         f"{len(problems)} issue(s) detected. Most urgent: {problems[0]['title']}",
    }

# ---------------------------------------------------------------------------
# Bottleneck Detector — "Why Am I Stuck?"
# ---------------------------------------------------------------------------

@app.get("/bottleneck")
def get_bottleneck():
    """
    Analyzes mood, energy, focus trends + habits + goals to identify the
    primary bottleneck and generate an AI recovery plan.
    """
    all_light = fetch_all_entries_light()
    if len(all_light) < 3:
        return {
            "bottleneck": None,
            "message":    "Need at least 3 journal entries to detect bottlenecks.",
        }

    recent = all_light[-10:]
    moods    = [e["mood"]   for e in recent]
    energies = [e["energy"] for e in recent]
    focuses  = [e["focus"]  for e in recent]

    m_slope = linear_slope(moods)
    e_slope = linear_slope(energies)
    f_slope = linear_slope(focuses)

    avg_mood   = round(sum(moods)    / len(moods),    1)
    avg_energy = round(sum(energies) / len(energies), 1)
    avg_focus  = round(sum(focuses)  / len(focuses),  1)

    analytics = predictive_analytics()
    streaks   = _compute_streaks_raw()
    goal_data = build_goal_summary()

    # Score each potential bottleneck
    candidates = []

    if avg_energy <= 2.5 or e_slope < -0.1:
        score = round((3 - avg_energy) * 30 + max(0, -e_slope * 100))
        candidates.append(("Low Energy", score, [
            f"Average energy: {avg_energy}/5",
            f"Energy trend: {describe_trend(e_slope)}",
            "Missed habits correlate with low energy days",
        ], [
            "Prioritize sleep — aim for 7-8 hours tonight",
            "Complete only one small quest today",
            "Reduce active goals to 2 maximum this week",
            "Add a 10-minute walk to your morning routine",
        ]))

    if avg_mood <= 2.5 or m_slope < -0.1:
        score = round((3 - avg_mood) * 30 + max(0, -m_slope * 100))
        candidates.append(("Low Mood", score, [
            f"Average mood: {avg_mood}/5",
            f"Mood trend: {describe_trend(m_slope)}",
        ], [
            "Write about what's bothering you in your next journal entry",
            "Complete one physical habit today (movement improves mood)",
            "Reach out to someone you trust",
            "Lower goal expectations for this week — rest is productive",
        ]))

    if avg_focus <= 2.5 or f_slope < -0.1:
        score = round((3 - avg_focus) * 25 + max(0, -f_slope * 80))
        candidates.append(("Poor Focus", score, [
            f"Average focus: {avg_focus}/5",
            f"Focus trend: {describe_trend(f_slope)}",
        ], [
            "Turn off all notifications for 45 minutes and do one task",
            "Start with the smallest possible action on your main goal",
            "Use the Pomodoro technique: 25 min work, 5 min break",
            "Identify and remove your top 2 distractions",
        ]))

    # Goal stagnation from quests (not journal)
    cat_health = build_category_health(goal_data)
    stale_count = sum(1 for c in cat_health if c["stale"])
    if stale_count > 0:
        score = stale_count * 40
        candidates.append(("Goal Stagnation", score, [
            f"{stale_count} goal categor{'y' if stale_count==1 else 'ies'} inactive for 7+ days",
            f"Goals at failure risk: {len(analytics.get('goal_failure_risk', []))}",
        ], [
            "Break your biggest goal into tasks under 30 minutes each",
            "Delete or pause one goal you haven't touched in 2 weeks",
            "Set a specific time block today for your most important quest",
            "Ask yourself: is this goal still meaningful to you?",
        ]))

    if analytics.get("streak_at_risk"):
        score = len(analytics["streak_at_risk"]) * 35
        candidates.append(("Habit Inconsistency", score, [
            f"Habits at risk: {', '.join(analytics['streak_at_risk'])}",
            f"Consistency score: {analytics.get('consistency_score', 0)}%",
        ], [
            f"Log '{analytics['streak_at_risk'][0]}' right now — it takes 2 minutes",
            "Set a phone reminder at a fixed time daily for your habits",
            "Reduce to 2 keystone habits if you're logging more than 5",
            "Use your recovery tokens if a streak is worth saving",
        ]))

    if not candidates:
        candidates.append(("No Clear Bottleneck", 0, [
            f"Mood: {avg_mood}/5 — OK",
            f"Energy: {avg_energy}/5 — OK",
            f"Focus: {avg_focus}/5 — OK",
        ], [
            "Keep the momentum going",
            "Consider adding a harder challenge or new skill node",
            "Review your monthly goals and raise the bar",
        ]))

    # Sort by score descending, take top
    candidates.sort(key=lambda c: c[1], reverse=True)
    primary_name, confidence_raw, evidence, recovery = candidates[0]
    confidence = min(round(confidence_raw / max(c[1] for c in candidates) * 100) if candidates and candidates[0][1] > 0 else 50, 99)

    # AI generates a personalized recovery plan
    try:
        prompt = f"""You are LiAInne, a personal growth coach.

Bottleneck analysis:
Primary issue: {primary_name}
Evidence: {evidence}
User stats: mood {avg_mood}/5, energy {avg_energy}/5, focus {avg_focus}/5

Write a 3-sentence personalized recovery message:
1. Acknowledge what the data shows (be specific, not generic)
2. Give the single most impactful action for TODAY
3. One encouraging sentence about why this will pass

Be direct, warm, and specific. Max 80 words. Sound like a coach who cares."""

        ai_response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.75, max_tokens=150,
        )
        ai_message = ai_response.choices[0].message.content.strip()
    except Exception:
        ai_message = None

    return {
        "bottleneck":    primary_name,
        "confidence":    confidence,
        "evidence":      evidence,
        "recovery_plan": recovery,
        "ai_message":    ai_message,
        "all_scores":    [{"name": c[0], "score": c[1]} for c in candidates],
        "stats": {
            "avg_mood":   avg_mood,
            "avg_energy": avg_energy,
            "avg_focus":  avg_focus,
        },
    }

# ---------------------------------------------------------------------------
# Serve static files
# ---------------------------------------------------------------------------
app.mount("/", StaticFiles(directory="static", html=True), name="static")