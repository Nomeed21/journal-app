import os
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
# Models
# ---------------------------------------------------------------------------


class EntryCreate(BaseModel):
    title: str
    content: str
    mood: int
    goal_progress: int
    tags: list[str] = []
    entry_type: str = "free"   # "morning" | "night" | "free"
    energy: int = 3            # 1-5
    focus: int = 3             # 1-5


class ChatTurn(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class ChatMessage(BaseModel):
    message: str
    history: list[ChatTurn] = []  # prior turns this session, sent back by the client


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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def generate_embedding(text: str) -> list[float]:
    embedding = embedding_model.encode(text)
    return embedding.tolist()


def calc_streak(unique_dates_desc: list[str], today: str) -> int:
    """Given dates sorted descending (YYYY-MM-DD strings), count the current
    consecutive-day streak ending today or yesterday."""
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


def linear_slope(values: list) -> float:
    clean = [float(v) for v in values if v is not None]

    n = len(clean)
    if n < 2:
        return 0.0

    x_mean = (n - 1) / 2
    y_mean = sum(clean) / n

    numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(clean))
    denominator = sum((i - x_mean) ** 2 for i in range(n))

    return numerator / denominator if denominator else 0.0



def safe_int(value, default=0):
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_rating(value, default=3):
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def compute_correlations(entries: list[dict]):
    days = {i: {"moods": [], "goals": []} for i in range(7)}

    for entry in entries:
        created_at = entry.get("created_at")
        if not created_at:
            continue

        dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        dow = dt.weekday()

        days[dow]["moods"].append(safe_rating(entry.get("mood")))
        days[dow]["goals"].append(safe_int(entry.get("goal_progress")))

    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    correlations = []

    for i, name in enumerate(day_names):
        if days[i]["moods"]:
            correlations.append({
                "day": name,
                "avg_mood": round(sum(days[i]["moods"]) / len(days[i]["moods"]), 1),
                "avg_goal": round(sum(days[i]["goals"]) / len(days[i]["goals"]), 1),
            })
        else:
            correlations.append({"day": name, "avg_mood": 0, "avg_goal": 0})

    return correlations


def compute_streaks(habit_rows: list[dict]):
    habit_dates = defaultdict(list)

    for row in habit_rows:
        habit_dates[row["name"]].append(row["completed_at"])

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    streaks = {}
    for name, dates in habit_dates.items():
        unique_dates = sorted(set(dates), reverse=True)
        streaks[name] = {
            "current_streak": calc_streak(unique_dates, today),
            "total_logs": len(dates),
        }

    return streaks


def describe_trend(slope: float, threshold: float = 0.05) -> str:
    if slope > threshold:
        return "trending up"
    if slope < -threshold:
        return "trending down"
    return "flat"


# ---------------------------------------------------------------------------
# Entry CRUD
# ---------------------------------------------------------------------------


@app.post("/entries")
def create_entry(entry: EntryCreate):
    combined_text = (
        f"Title: {entry.title}. "
        f"Content: {entry.content}. "
        f"Mood: {entry.mood}/5. Energy: {entry.energy}/5. "
        f"Focus: {entry.focus}/5. Goal progress: {entry.goal_progress}%."
    )
    embedding = generate_embedding(combined_text)

    data = {
        "title": entry.title,
        "content": entry.content,
        "mood": entry.mood,
        "goal_progress": entry.goal_progress,
        "energy": entry.energy,
        "focus": entry.focus,
        "entry_type": entry.entry_type,
        "embedding": embedding,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "tags": entry.tags,
    }

    result = supabase.table("journal_entries").insert(data).execute()
    return {"status": "created", "entry": result.data[0]}


@app.get("/entries")
def get_entries(
    tag: Optional[str] = None,
    keyword: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
):
    query = supabase.table("journal_entries").select(
        "id, title, content, mood, goal_progress, energy, focus, entry_type, tags, created_at"
    )

    if tag:
        query = query.contains("tags", [tag])
    if keyword:
        query = query.or_(f"title.ilike.%{keyword}%,content.ilike.%{keyword}%")
    if start_date:
        query = query.gte("created_at", start_date)
    if end_date:
        query = query.lte("created_at", end_date)

    result = query.order("created_at", desc=True).execute()
    return result.data


@app.get("/entries/trends")
def get_trends(days: int = 30):
    start = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    result = (
        supabase.table("journal_entries")
        .select("mood, goal_progress, energy, focus, created_at")
        .gte("created_at", start)
        .order("created_at")
        .execute()
    )

    daily = {}
    for entry in result.data:
        date = entry["created_at"][:10]
        if date not in daily:
            daily[date] = {"moods": [], "goals": [], "energies": [], "focuses": []}
        daily[date]["moods"].append(entry["mood"])
        daily[date]["goals"].append(entry["goal_progress"])
        daily[date]["energies"].append(entry.get("energy") or 3)
        daily[date]["focuses"].append(entry.get("focus") or 3)

    trends = []
    for date, values in sorted(daily.items()):
        trends.append(
            {
                "date": date,
                "avg_mood":   round(sum(values["moods"])    / len(values["moods"]), 1),
                "avg_goal":   round(sum(values["goals"])    / len(values["goals"]), 1),
                "avg_energy": round(sum(values["energies"]) / len(values["energies"]), 1),
                "avg_focus":  round(sum(values["focuses"])  / len(values["focuses"]), 1),
            }
        )

    return trends


@app.get("/entries/correlations")
def get_correlations():
    result = (
        supabase.table("journal_entries")
        .select("mood, goal_progress, created_at")
        .execute()
    )

    days = {i: {"moods": [], "goals": []} for i in range(7)}
    for entry in result.data:
        dt = datetime.fromisoformat(entry["created_at"].replace("Z", "+00:00"))
        dow = dt.weekday()
        days[dow]["moods"].append(entry["mood"])
        days[dow]["goals"].append(entry["goal_progress"])

    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    correlations = []
    for i, name in enumerate(day_names):
        if days[i]["moods"]:
            correlations.append(
                {
                    "day": name,
                    "avg_mood": round(sum(days[i]["moods"]) / len(days[i]["moods"]), 1),
                    "avg_goal": round(sum(days[i]["goals"]) / len(days[i]["goals"]), 1),
                }
            )
        else:
            correlations.append({"day": name, "avg_mood": 0, "avg_goal": 0})

    return correlations


@app.get("/entries/{entry_id}")
def get_entry(entry_id: int):
    result = (
        supabase.table("journal_entries")
        .select("id, title, content, mood, goal_progress, tags, created_at")
        .eq("id", entry_id)
        .single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Entry not found")
    return result.data


@app.put("/entries/{entry_id}")
def update_entry(entry_id: int, entry: EntryCreate):
    combined_text = (
        f"Title: {entry.title}. "
        f"Content: {entry.content}. "
        f"Mood: {entry.mood}/5. Energy: {entry.energy}/5. "
        f"Focus: {entry.focus}/5. Goal progress: {entry.goal_progress}%."
    )
    embedding = generate_embedding(combined_text)

    data = {
        "title": entry.title,
        "content": entry.content,
        "mood": entry.mood,
        "goal_progress": entry.goal_progress,
        "energy": entry.energy,
        "focus": entry.focus,
        "entry_type": entry.entry_type,
        "tags": entry.tags,
        "embedding": embedding,
    }

    result = supabase.table("journal_entries").update(data).eq("id", entry_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Entry not found")
    return {"status": "updated", "entry": result.data[0]}


@app.delete("/entries/{entry_id}")
def delete_entry(entry_id: int):
    result = supabase.table("journal_entries").delete().eq("id", entry_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Entry not found")
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# Habits
# ---------------------------------------------------------------------------


@app.post("/habits")
def log_habit(habit: HabitLog):
    data = {
        "name": habit.name,
        "completed_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    result = supabase.table("habits").insert(data).execute()
    return {"status": "logged", "habit": result.data[0]}


@app.get("/habits/streaks")
def get_streaks():
    result = (
        supabase.table("habits")
        .select("name, completed_at")
        .order("completed_at", desc=True)
        .execute()
    )

    habit_dates = defaultdict(list)
    for row in result.data:
        habit_dates[row["name"]].append(row["completed_at"])

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    streaks = {}
    for name, dates in habit_dates.items():
        unique_dates = sorted(set(dates), reverse=True)
        streaks[name] = {
            "current_streak": calc_streak(unique_dates, today),
            "total_logs": len(dates),
        }

    return streaks


# ---------------------------------------------------------------------------
# Coach context builder
#
# This is the core fix: instead of handing the LLM a handful of raw entries
# and asking it to "notice trends," we pre-compute the trend math in Python
# (which is reliable) and only use the LLM for what it's actually good at —
# reading nuance in text and turning numbers into advice.
#
# Tiering strategy for hundreds-to-thousands of entries:
#   - Last RECENT_DAYS days  -> full entry text, verbatim (detail recent)
#   - Everything older       -> collapsed into weekly stat summaries
#                                (avg mood, avg goal, entry count) — no raw text
#   - Semantic search        -> pulls specific OLD entries back in by relevance
#                                to the user's current question, so "how was
#                                I feeling in March" still works without
#                                sending every entry every time.
# ---------------------------------------------------------------------------

RECENT_DAYS = 14
MAX_WEEKLY_SUMMARY_ROWS = 26  # ~6 months of weekly rows before we'd want to
# bucket by month instead; safe for "low 1000s"
# of entries since this is stats, not raw text.


def fetch_all_entries_light():
    result = (
        supabase.table("journal_entries")
        .select("id, mood, goal_progress, energy, focus, entry_type, created_at")
        .order("created_at")
        .execute()
    )

    entries = []

    for e in result.data:
        entries.append({
            "id": e["id"],
            "mood": safe_rating(e.get("mood")),
            "goal_progress": safe_int(e.get("goal_progress")),
            "energy": safe_rating(e.get("energy")),
            "focus": safe_rating(e.get("focus")),
            "entry_type": e.get("entry_type") or "free",
            "created_at": e["created_at"],
        })

    return entries


def build_recent_text_block(today_iso: str) -> str:
    """Full text for entries in the last RECENT_DAYS days."""
    start = (datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)).isoformat()
    result = (
        supabase.table("journal_entries")
        .select("id, title, content, mood, goal_progress, created_at, tags")
        .gte("created_at", start)
        .order("created_at", desc=True)
        .execute()
    )
    if not result.data:
        return "No entries in the last 14 days."

    parts = []
    for e in result.data:
        tags = f" [tags: {', '.join(e['tags'])}]" if e.get("tags") else ""
        etype = e.get("entry_type", "free")
        energy = e.get("energy") or 3
        focus  = e.get("focus")  or 3
        parts.append(
            f"[{e['created_at'][:10]}] [{etype}] "
            f"(Mood: {e['mood']}/5, Energy: {energy}/5, Focus: {focus}/5, Goal: {e['goal_progress']}%){tags} "
            f"{e['title']}: {e['content']}"
        )
    return "\n\n".join(parts)


def build_weekly_summary_block(all_light_entries: list[dict]) -> str:
    """Collapse everything older than RECENT_DAYS into weekly avg stats."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)
    older = [
        e
        for e in all_light_entries
        if datetime.fromisoformat(e["created_at"].replace("Z", "+00:00")) < cutoff
    ]
    if not older:
        return "No older entries yet — history is limited to the recent period above."

    weekly = defaultdict(lambda: {"moods": [], "goals": [], "count": 0})
    for e in older:
        dt = datetime.fromisoformat(e["created_at"].replace("Z", "+00:00"))
        # ISO year-week as a stable bucket key
        year, week, _ = dt.isocalendar()
        key = f"{year}-W{week:02d}"
        weekly[key]["moods"].append(e["mood"])
        weekly[key]["goals"].append(e["goal_progress"])
        weekly[key]["count"] += 1

    rows = []
    for key in sorted(weekly.keys()):
        v = weekly[key]
        avg_mood = round(sum(v["moods"]) / len(v["moods"]), 1)
        avg_goal = round(sum(v["goals"]) / len(v["goals"]), 1)
        rows.append(
            f"{key}: avg mood {avg_mood}/5, avg goal {avg_goal}%, {v['count']} entries"
        )

    # If history is very long, keep it bounded: earliest rows + most recent
    # rows, with a note in between, rather than truncating silently.
    if len(rows) > MAX_WEEKLY_SUMMARY_ROWS:
        head = rows[: MAX_WEEKLY_SUMMARY_ROWS // 2]
        tail = rows[-(MAX_WEEKLY_SUMMARY_ROWS // 2) :]
        omitted = len(rows) - len(head) - len(tail)
        rows = (
            head
            + [f"... ({omitted} earlier weeks omitted, available via search) ..."]
            + tail
        )

    return "\n".join(rows)


def build_trend_stats_block(all_light_entries: list[dict]) -> str:
    """Overall slope/streak-style stats computed in Python, not by the LLM."""
    if not all_light_entries:
        return "No data yet."

    moods = [e["mood"] for e in all_light_entries]
    goals = [e["goal_progress"] for e in all_light_entries]

    mood_slope = linear_slope(moods)
    goal_slope = linear_slope(goals)

    # last 7 vs previous 7 entries, for a concrete "recent shift" number
    recent7 = all_light_entries[-7:]
    prior7 = all_light_entries[-14:-7] if len(all_light_entries) >= 14 else []

    def avg(lst, key):
        return round(sum(e[key] for e in lst) / len(lst), 1) if lst else None

    lines = [
        f"Overall mood trend: {describe_trend(mood_slope)} (slope {mood_slope:.3f}) "
        f"over {len(moods)} total entries.",
        f"Overall goal_progress trend: {describe_trend(goal_slope)} (slope {goal_slope:.3f}) "
        f"over {len(goals)} total entries.",
    ]

    if prior7:
        lines.append(
            f"Last 7 entries avg: mood {avg(recent7, 'mood')}/5, goal {avg(recent7, 'goal_progress')}%. "
            f"Previous 7 entries avg: mood {avg(prior7, 'mood')}/5, goal {avg(prior7, 'goal_progress')}%."
        )
    else:
        lines.append(
            f"Last 7 entries avg: mood {avg(recent7, 'mood')}/5, goal {avg(recent7, 'goal_progress')}%. "
            f"(Not enough history yet for a prior-7 comparison.)"
        )

    return "\n".join(lines)


def build_day_of_week_block() -> str:
    correlations = get_correlations()
    rows = [
        f"{c['day']}: avg mood {c['avg_mood']}/5, avg goal {c['avg_goal']}%"
        for c in correlations
        if c["avg_mood"] > 0
    ]
    if not rows:
        return "Not enough data yet for day-of-week patterns."
    return "\n".join(rows)


def build_habit_block() -> str:
    result = (
        supabase.table("habits")
        .select("name, completed_at")
        .order("completed_at", desc=True)
        .execute()
    )
    habit_dates = defaultdict(list)
    for row in result.data:
        habit_dates[row["name"]].append(row["completed_at"])

    if not habit_dates:
        return "No habits tracked yet."

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = []
    for name, dates in habit_dates.items():
        unique_dates = sorted(set(dates), reverse=True)
        streak = calc_streak(unique_dates, today)
        last_done = unique_dates[0] if unique_dates else "never"
        lines.append(
            f"- {name}: {streak}-day streak, {len(dates)} total logs, last done {last_done}"
        )
    return "\n".join(lines)


def build_semantic_matches_block(message: str, exclude_recent_ids: set[int]) -> str:
    """Pull in specific OLDER entries relevant to the user's question, so
    questions like 'how was I doing in March' still surface real detail
    even though March is outside the RECENT_DAYS full-text window."""
    query_embedding = generate_embedding(message)
    matches = supabase.rpc(
        "match_entries",
        {
            "query_embedding": query_embedding,
            "match_threshold": 0.3,
            "match_count": 5,
        },
    ).execute()

    relevant_old = [e for e in matches.data if e["id"] not in exclude_recent_ids]
    if not relevant_old:
        return ""

    parts = []
    for e in relevant_old:
        parts.append(
            f"[{e['created_at'][:10]}] (Mood: {e['mood']}/5, Goal: {e['goal_progress']}%) "
            f"{e['title']}: {e['content']}"
        )
    return "\n\n".join(parts)


def build_coach_context(message: str) -> str:
    today_iso = datetime.now(timezone.utc).isoformat()

    all_light = fetch_all_entries_light()
    recent_ids = {
        e["id"]
        for e in all_light
        if datetime.fromisoformat(e["created_at"].replace("Z", "+00:00"))
        >= datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)
    }

    recent_text = build_recent_text_block(today_iso)
    weekly_summary = build_weekly_summary_block(all_light)
    trend_stats = build_trend_stats_block(all_light)
    day_of_week = build_day_of_week_block()
    habits = build_habit_block()
    semantic_matches = build_semantic_matches_block(message, recent_ids)

    sections = [
        f"TREND STATISTICS (computed, trust these numbers over your own estimate):\n{trend_stats}",
        f"DAY-OF-WEEK PATTERNS (all-time averages):\n{day_of_week}",
        f"HABIT TRACKER:\n{habits}",
        f"RECENT ENTRIES (last {RECENT_DAYS} days, full text):\n{recent_text}",
        f"OLDER HISTORY (weekly averages, summarized):\n{weekly_summary}",
    ]

    if semantic_matches:
        sections.append(
            f"SPECIFIC OLDER ENTRIES RELEVANT TO THIS QUESTION:\n{semantic_matches}"
        )

    return "\n\n---\n\n".join(sections)


def build_ai_insight_context():
    all_light = fetch_all_entries_light()

    if len(all_light) < 3:
        return None

    moods = [e["mood"] for e in all_light]
    goals = [e["goal_progress"] for e in all_light]

    mood_slope = linear_slope(moods)
    goal_slope = linear_slope(goals)

    correlations = get_correlations()

    best_day = None
    valid_days = [d for d in correlations if d["avg_mood"] > 0]

    if valid_days:
        best_day = max(valid_days, key=lambda d: d["avg_mood"])

    streaks = get_streaks()

    strongest_habit = None
    longest_streak = 0

    if streaks:
        strongest_habit, stats = max(
            streaks.items(), key=lambda item: item[1]["current_streak"]
        )

        longest_streak = stats["current_streak"]

    avg_mood = round(sum(moods) / len(moods), 1)
    avg_goal = round(sum(goals) / len(goals), 1)

    return {
        "entries": len(all_light),
        "avg_mood": avg_mood,
        "avg_goal_progress": avg_goal,
        "mood_trend": describe_trend(mood_slope),
        "goal_trend": describe_trend(goal_slope, threshold=0.5),
        "best_day": best_day["day"] if best_day else None,
        "best_day_mood": best_day["avg_mood"] if best_day else None,
        "strongest_habit": strongest_habit,
        "habit_streak": longest_streak,
    }


def get_current_month_entries():
    now = datetime.now(timezone.utc)

    start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)

    result = (
        supabase.table("journal_entries")
        .select("title, content, mood, goal_progress, created_at")
        .gte("created_at", start.isoformat())
        .order("created_at")
        .execute()
    )

    return result.data


def build_monthly_review_context():
    entries = get_current_month_entries()

    if not entries:
        return None

    moods = [e["mood"] for e in entries]
    goals = [e["goal_progress"] for e in entries]

    avg_mood = round(sum(moods) / len(moods), 1)
    avg_goal = round(sum(goals) / len(goals), 1)

    mood_trend = describe_trend(linear_slope(moods))
    goal_trend = describe_trend(linear_slope(goals), threshold=0.5)

    correlations = get_correlations()

    valid_days = [d for d in correlations if d["avg_mood"] > 0]

    best_day = None

    if valid_days:
        best_day = max(valid_days, key=lambda d: d["avg_mood"])["day"]

    streaks = get_streaks()

    strongest_habit = None

    if streaks:
        strongest_habit = max(streaks.items(), key=lambda x: x[1]["current_streak"])[0]

    recent_entries = []

    for e in entries[-5:]:
        recent_entries.append(f"{e['title']}: {e['content'][:200]}")

    return {
        "entry_count": len(entries),
        "avg_mood": avg_mood,
        "avg_goal_progress": avg_goal,
        "mood_trend": mood_trend,
        "goal_trend": goal_trend,
        "best_day": best_day,
        "strongest_habit": strongest_habit,
        "recent_entries": recent_entries,
    }


# ---------------------------------------------------------------------------
# Goals
# ---------------------------------------------------------------------------


@app.post("/goals")
def create_goal(goal: GoalCreate):
    data = {
        "title": goal.title,
        "category": goal.category,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "is_completed": False,
    }

    result = supabase.table("goals").insert(data).execute()

    return {"status": "created", "goal": result.data[0]}


@app.get("/goals")
def get_goals():
    goals = supabase.table("goals").select("*").order("created_at", desc=True).execute()

    task_rows = supabase.table("goal_tasks").select("*").execute()

    tasks_by_goal = defaultdict(list)

    for task in task_rows.data:
        tasks_by_goal[task["goal_id"]].append(task)

    enriched = []

    for goal in goals.data:
        tasks = tasks_by_goal.get(goal["id"], [])

        total = len(tasks)
        completed = len([t for t in tasks if t["is_completed"]])

        progress = round(completed / total * 100) if total > 0 else 0

        goal["progress"] = progress
        goal["completed_tasks"] = completed
        goal["total_tasks"] = total

        enriched.append(goal)

    return enriched


@app.post("/goals/{goal_id}/tasks")
def create_task(goal_id: int, task: TaskCreate):

    result = (
        supabase.table("goal_tasks")
        .insert(
            {
                "goal_id": goal_id,
                "title": task.title,
                "is_completed": False,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        .execute()
    )

    return result.data[0]


@app.get("/goals/{goal_id}/tasks")
def get_tasks(goal_id: int):

    result = supabase.table("goal_tasks").select("*").eq("goal_id", goal_id).execute()

    return result.data


@app.put("/tasks/{task_id}")
def toggle_task(task_id: int):

    task = supabase.table("goal_tasks").select("*").eq("id", task_id).single().execute()

    updated = (
        supabase.table("goal_tasks")
        .update({"is_completed": not task.data["is_completed"]})
        .eq("id", task_id)
        .execute()
    )

    return updated.data[0]



@app.delete("/goals/{goal_id}")
def delete_goal(goal_id: int):
    # Delete all tasks for this goal first (no cascade assumed)
    supabase.table("goal_tasks").delete().eq("goal_id", goal_id).execute()
    result = supabase.table("goals").delete().eq("id", goal_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Goal not found")
    return {"status": "deleted"}


@app.delete("/tasks/{task_id}")
def delete_task(task_id: int):
    result = supabase.table("goal_tasks").delete().eq("id", task_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# Goal summary — category health + XP totals, shared by /insights,
# /daily-quest, and /monthly-review so all three see the same quest data.
# ---------------------------------------------------------------------------

XP_PER_TASK = 50
XP_PER_LEVEL = 500


def build_goal_summary() -> list[dict]:
    """
    Returns one dict per goal with tasks, completion counts, progress %,
    XP, level, and days_since_created (staleness proxy).
    """
    goals = supabase.table("goals").select("*").order("created_at", desc=True).execute()
    task_rows = supabase.table("goal_tasks").select("*").execute()

    tasks_by_goal: dict[int, list] = defaultdict(list)
    for task in task_rows.data:
        tasks_by_goal[task["goal_id"]].append(task)

    summary = []
    for goal in goals.data:
        tasks = tasks_by_goal.get(goal["id"], [])
        completed = len([t for t in tasks if t["is_completed"]])
        total = len(tasks)
        progress = round(completed / total * 100) if total > 0 else 0
        xp = completed * XP_PER_TASK
        level = xp // XP_PER_LEVEL + 1
        created = datetime.fromisoformat(goal["created_at"].replace("Z", "+00:00"))
        days_since_created = (datetime.now(timezone.utc) - created).days

        summary.append(
            {
                **goal,
                "tasks": tasks,
                "completed_tasks": completed,
                "total_tasks": total,
                "progress": progress,
                "xp": xp,
                "level": level,
                "days_since_created": days_since_created,
            }
        )
    return summary


def build_category_health(summary: list[dict]) -> list[dict]:
    """
    Per-category aggregation: total XP, completion rate, staleness flag.
    """
    by_cat: dict[str, dict] = {}
    for g in summary:
        cat = g.get("category", "Other")
        if cat not in by_cat:
            by_cat[cat] = {"xp": 0, "completed": 0, "total": 0, "days": []}
        by_cat[cat]["xp"] += g["xp"]
        by_cat[cat]["completed"] += g["completed_tasks"]
        by_cat[cat]["total"] += g["total_tasks"]
        by_cat[cat]["days"].append(g["days_since_created"])

    health = []
    for cat, data in by_cat.items():
        rate = round(data["completed"] / data["total"] * 100) if data["total"] > 0 else 0
        oldest = max(data["days"])
        stale = oldest > 7 and rate < 50
        health.append(
            {
                "category": cat,
                "total_xp": data["xp"],
                "completion_rate": rate,
                "stale": stale,
                "oldest_goal_days": oldest,
            }
        )
    return sorted(health, key=lambda x: x["total_xp"], reverse=True)


@app.get("/goals/summary")
def goals_summary():
    """Full RPG view: goals + tasks + XP + level. Replaces raw /goals for the
    frontend card renderer so it only needs one round-trip."""
    return build_goal_summary()


@app.post("/daily-quest")
def daily_quest():
    """
    Picks today's most impactful pending quest via Groq.
    Moved from the browser (where it hit the Anthropic API directly) to the
    backend so no API keys are ever exposed to the client.
    """
    import json

    summary = build_goal_summary()

    pending_lines = []
    for g in summary:
        pending = [t["title"] for t in g["tasks"] if not t["is_completed"]]
        if pending:
            pending_lines.append(
                f'Goal "{g["title"]}" [{g["category"]}] — ' +
                f'pending: {", ".join(pending[:3])}'
            )

    if not pending_lines:
        return {"task": None, "message": "All quests complete! Add new ones to keep going."}

    quest_context = "\n".join(pending_lines)

    recent = fetch_all_entries_light()[-7:]
    avg_mood = round(sum(e["mood"] for e in recent) / len(recent), 1) if recent else None
    mood_note = f"Recent average mood: {avg_mood}/5." if avg_mood else ""

    prompt = f"""You are a quest generator for a personal journal RPG.

Active goals and pending quests:
{quest_context}

{mood_note}

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
        temperature=0.7,
        max_tokens=300,
    )

    raw = response.choices[0].message.content.strip()
    try:
        quest = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Quest generation failed — invalid JSON from model.")

    return quest


# ---------------------------------------------------------------------------
# Action Engine
#
# Philosophy: don't just report patterns — prescribe actions.
# Called automatically after every journal save. Evaluates four triggers:
#   1. Mood drop   — mood fell 2+ pts vs the prior entry
#   2. Stale goal  — a goal category untouched for 5+ days
#   3. Streak risk — a habit logged yesterday but not yet today
#   4. Zero-progress goal — a goal with tasks but 0% done after 7+ days
#
# Only fires the LLM when at least one trigger is true. Returns one
# prescribed action (not a menu of options) and optionally auto-creates
# it as a quest under the relevant goal.
# ---------------------------------------------------------------------------

def detect_triggers(mood: int, content: str) -> dict:
    """
    Evaluate all four trigger conditions. Returns a dict with:
      - triggered: bool
      - reasons: list of plain-English trigger descriptions
      - context: structured data for the prompt
    """
    reasons = []
    context_parts = []

    # ── 1. Mood drop ──────────────────────────────────────────────────────
    all_entries = fetch_all_entries_light()
    if len(all_entries) >= 2:
        prev_mood = all_entries[-2]["mood"]   # second-to-last (just before this save)
        drop = prev_mood - mood
        if drop >= 2:
            reasons.append(f"mood dropped {drop} points (from {prev_mood} to {mood})")
            context_parts.append(f"Mood drop: {prev_mood} → {mood}/5")

    # ── 2. Stale goal category ────────────────────────────────────────────
    goal_data = build_goal_summary()
    cat_health = build_category_health(goal_data)
    stale_cats = [c for c in cat_health if c["stale"]]
    if stale_cats:
        worst = stale_cats[0]
        reasons.append(
            f"{worst['category']} goals inactive for {worst['oldest_goal_days']}+ days"
        )
        context_parts.append(
            f"Stale category: {worst['category']} ({worst['completion_rate']}% done, "
            f"{worst['oldest_goal_days']} days since created)"
        )

    # ── 3. Streak at risk ────────────────────────────────────────────────
    habit_result = (
        supabase.table("habits")
        .select("name, completed_at")
        .order("completed_at", desc=True)
        .execute()
    )
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    habit_dates: dict[str, list[str]] = defaultdict(list)
    for row in habit_result.data:
        habit_dates[row["name"]].append(row["completed_at"])

    at_risk = []
    for name, dates in habit_dates.items():
        unique = sorted(set(dates), reverse=True)
        logged_yesterday = unique and unique[0] == yesterday
        logged_today = today in unique
        if logged_yesterday and not logged_today:
            at_risk.append(name)

    if at_risk:
        reasons.append(f"streak at risk for: {', '.join(at_risk)}")
        context_parts.append(f"Habits not yet done today (streak at risk): {', '.join(at_risk)}")

    # ── 4. Zero-progress goals ────────────────────────────────────────────
    zero_goals = [
        g for g in goal_data
        if g["total_tasks"] > 0
        and g["progress"] == 0
        and g["days_since_created"] >= 7
    ]
    if zero_goals:
        names = ", ".join(g["title"] for g in zero_goals[:2])
        reasons.append(f"goals with 0% progress after 7+ days: {names}")
        context_parts.append(f"Zero-progress goals (7+ days old): {names}")

    return {
        "triggered": len(reasons) > 0,
        "reasons": reasons,
        "context": "\n".join(context_parts),
        "goal_data": goal_data,
        "stale_cats": stale_cats,
        "at_risk_habits": at_risk,
        "zero_goals": zero_goals,
    }


@app.post("/action-engine")
def action_engine(req: ActionEngineRequest):
    """
    Evaluate triggers and, if any fire, use Groq to prescribe one concrete
    action. Optionally auto-creates the action as a quest in the most relevant
    goal so it appears in the user's quest list immediately.
    """
    import json as _json

    triggers = detect_triggers(req.mood, req.content)

    if not triggers["triggered"]:
        return {"triggered": False, "action": None}

    # Build goal context for the prompt
    goal_data = triggers["goal_data"]
    pending_quests = []
    for g in goal_data:
        pending = [t["title"] for t in g["tasks"] if not t["is_completed"]]
        if pending:
            pending_quests.append(
                f'Goal "{g["title"]}" [{g["category"]}] — pending: {", ".join(pending[:2])}'
            )

    pending_block = "\n".join(pending_quests) if pending_quests else "No active quests yet."

    prompt = f"""You are a behavior coach inside a personal journal app.

The user just saved a journal entry. These problems were detected:
{triggers["context"]}

Entry content: "{req.content[:300]}"

Active goals and pending quests:
{pending_block}

Your job: prescribe ONE specific action that directly addresses the most urgent problem.

Rules:
- If mood dropped, prescribe a recovery action (short walk, breathing, one small win).
- If a goal category is stale, prescribe the smallest concrete next step inside that category.
- If a habit streak is at risk, prescribe doing that habit right now.
- If a goal has 0% progress, prescribe the very first task to break inertia.
- The action should take 5-30 minutes maximum.
- Be specific. "Go outside for 15 minutes" not "take a break".
- If there is an existing pending quest that fits, use its exact title.
- Otherwise invent a new specific micro-task.

Reply ONLY in this JSON format (no markdown, no extra text):
{{
  "action": "specific task title",
  "reason": "one sentence — which trigger this addresses and why this action",
  "trigger_type": "mood_drop|stale_goal|streak_risk|zero_progress",
  "category": "the relevant goal category or Wellness",
  "xp": a number 20-80,
  "duration_minutes": a number 5-30,
  "is_existing_quest": true or false,
  "goal_title": "title of the goal to add this to, or null if no match"
}}"""

    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.6,
        max_tokens=300,
    )

    raw = response.choices[0].message.content.strip()
    try:
        action = _json.loads(raw)
    except _json.JSONDecodeError:
        return {"triggered": True, "action": None, "error": "parse_failed"}

    # Auto-create the quest if it's a new task and a matching goal exists
    created_quest = None
    if not action.get("is_existing_quest") and action.get("goal_title"):
        # Find the goal by title
        match = next(
            (g for g in goal_data if g["title"].lower() == action["goal_title"].lower()),
            None,
        )
        if match:
            result = (
                supabase.table("goal_tasks")
                .insert({
                    "goal_id": match["id"],
                    "title": action["action"],
                    "is_completed": False,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })
                .execute()
            )
            if result.data:
                created_quest = result.data[0]

    return {
        "triggered": True,
        "reasons": triggers["reasons"],
        "action": action,
        "quest_created": created_quest is not None,
        "quest": created_quest,
    }

# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_TEMPLATE = (
    "Your name is LiAInne. You are a warm but honest personal coach. "
    "You are not a therapist, doctor, or crisis counselor. You help the user "
    "notice patterns, be honest with themselves, and choose the next useful action.\n\n"
    "You have access to the user's journal context: recent entries, mood scores, "
    "goal progress, habit streaks, day-of-week patterns, trend summaries, and "
    "older relevant entries. Use this information privately to understand the "
    "user's situation. Do not read the data back like a report.\n\n"
    "Before answering, privately decide three things:\n"
    "1. What is the user's real problem right now?\n"
    "2. What is the most useful pattern or detail from their journal?\n"
    "3. What is one practical next step they can take today?\n\n"
    "Your response should usually include:\n"
    "- one honest observation,\n"
    "- one supportive but direct piece of advice,\n"
    "- one small action the user can do today.\n\n"
    "Give advice that is specific, grounded, kind, and actionable. "
    "Do not give a long list of options unless the user explicitly asks for one. "
    "Choose the most useful point and say it clearly.\n\n"
    "If the user's message is vague, ask one sharp follow-up question instead of guessing. "
    "If the user is venting, validate briefly, then help them move toward clarity. "
    "If the user asks what to do, give a concrete recommendation, not a menu of possibilities. "
    "If their journal data does not support what they are saying, gently point out the mismatch. "
    "Never pretend certainty. Use phrases like 'it looks like' or 'I might be wrong, but' when appropriate.\n\n"
    "Style rules:\n"
    "- Talk like a thoughtful friend who pays attention.\n"
    "- Be warm, direct, and concise.\n"
    "- Default to 2-4 short sentences.\n"
    "- Do not use bullet points unless the user asks for a breakdown.\n"
    "- Do not say 'slope,' 'trend value,' or summarize every stat.\n"
    "- Use at most one specific number or date if it strengthens the advice.\n"
    "- Do not diagnose the user or make medical claims.\n\n"
    "Safety rules:\n"
    "If the user mentions self-harm, suicide, abuse, immediate danger, or feeling unable "
    "to stay safe, respond with care and urgency. Encourage them to contact local emergency "
    "services, a crisis hotline, or a trusted person nearby. Do not try to coach them through "
    "danger as if it is a normal productivity problem.\n\n"
    "A strong response sounds like this:\n"
    "'You sound drained, not lazy. It looks like when your mood dips, your goals start "
    "feeling impossible instead of just hard. Don’t try to fix the whole week tonight. "
    "Pick one tiny thing you can finish in 10 minutes, then stop and call that a win.'\n\n"
    "{context}"
)

MAX_HISTORY_TURNS = 12  # ~6 back-and-forth exchanges; keeps token usage/cost
# bounded since the client resends history every call


@app.post("/chat")
def chat(msg: ChatMessage):
    context = build_coach_context(msg.message)
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(context=context)

    # Validate and trim client-supplied history defensively — this is
    # untrusted input even though it's "our own frontend," since a stale
    # client, bug, or direct API call could send garbage roles.
    trimmed_history = msg.history[-MAX_HISTORY_TURNS:]
    history_messages = [
        {"role": turn.role, "content": turn.content}
        for turn in trimmed_history
        if turn.role in ("user", "assistant") and turn.content.strip()
    ]

    messages = (
        [{"role": "system", "content": system_prompt}]
        + history_messages
        + [{"role": "user", "content": msg.message}]
    )

    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages,
        temperature=0.8,
        max_tokens=1024,
    )

    return {"response": response.choices[0].message.content}


@app.get("/insights")
def get_insights():
    all_light = fetch_all_entries_light()

    if len(all_light) < 3:
        return {
            "insights": [
                {
                    "type": "info",
                    "title": "Getting Started",
                    "message": "Keep journaling. More entries are needed before meaningful patterns can be detected.",
                }
            ]
        }

    insights = []

    # ---------------------------------------
    # Mood Trend
    # ---------------------------------------
    moods = [e["mood"] for e in all_light]
    mood_slope = linear_slope(moods)

    if mood_slope > 0.05:
        insights.append(
            {
                "type": "success",
                "title": "Mood Trend",
                "message": "Your mood has been improving over time.",
                "recommendation": "Review your recent entries and identify what has been helping.",
            }
        )
    elif mood_slope < -0.05:
        insights.append(
            {
                "type": "warning",
                "title": "Mood Trend",
                "message": "Your mood has been gradually declining.",
                "recommendation": "Review your last few entries and look for recurring stressors.",
            }
        )

    # ---------------------------------------
    # Goal Trend
    # ---------------------------------------
    goals = [e["goal_progress"] for e in all_light]
    goal_slope = linear_slope(goals)

    if goal_slope > 0.5:
        insights.append(
            {
                "type": "success",
                "title": "Goal Progress",
                "message": "Your goal progress is trending upward.",
                "recommendation": "Keep the current pace and focus on consistency.",
            }
        )
    elif goal_slope < -0.5:
        insights.append(
            {
                "type": "warning",
                "title": "Goal Progress",
                "message": "Goal progress has slowed recently.",
                "recommendation": "Break your goals into smaller daily actions.",
            }
        )

    # ---------------------------------------
    # Best Day
    # ---------------------------------------
    correlations = get_correlations()

    valid_days = [d for d in correlations if d["avg_mood"] > 0]

    if valid_days:
        best_day = max(valid_days, key=lambda d: d["avg_mood"])

        insights.append(
            {
                "type": "observation",
                "title": "Best Day",
                "message": f"{best_day['day']} is your strongest day with an average mood of {best_day['avg_mood']}/5.",
                "recommendation": f"Schedule important work on {best_day['day']} whenever possible.",
            }
        )

    # ---------------------------------------
    # Habits
    # ---------------------------------------
    streaks = get_streaks()

    if streaks:
        best_habit = max(streaks.items(), key=lambda item: item[1]["current_streak"])

        habit_name = best_habit[0]
        streak = best_habit[1]["current_streak"]

        if streak >= 3:
            insights.append(
                {
                    "type": "success",
                    "title": "Strong Habit",
                    "message": f"'{habit_name}' currently has a {streak}-day streak.",
                    "recommendation": "Protect this habit. It is becoming part of your identity.",
                }
            )

    # ---------------------------------------
    # Quest / Category Health
    # ---------------------------------------
    goal_data = build_goal_summary()
    if goal_data:
        category_health = build_category_health(goal_data)

        best_cat = next((c for c in category_health if c["total_xp"] > 0), None)
        if best_cat:
            insights.append(
                {
                    "type": "success",
                    "title": "Quest Progress",
                    "message": (
                        f"You're progressing fastest in {best_cat['category']} "
                        f"({best_cat['completion_rate']}% complete, {best_cat['total_xp']} XP earned)."
                    ),
                    "recommendation": (
                        f"Keep the momentum in {best_cat['category']} and consider "
                        "adding a harder quest to the list."
                    ),
                }
            )

        for s in [c for c in category_health if c["stale"]][:2]:
            insights.append(
                {
                    "type": "warning",
                    "title": f"{s['category']} Stalled",
                    "message": (
                        f"{s['category']} goals haven't had new activity in over a week "
                        f"and are only {s['completion_rate']}% complete."
                    ),
                    "recommendation": f"Open a {s['category']} quest today, even a small one.",
                }
            )

    if not insights:
        insights.append(
            {
                "type": "info",
                "title": "No Strong Patterns Yet",
                "message": "No significant trends detected.",
                "recommendation": "Keep journaling consistently.",
            }
        )

    return {"insights": insights}


@app.get("/ai-insight")
def ai_insight():
    stats = build_ai_insight_context()

    if not stats:
        return {
            "insight": "Keep journaling. I need a little more data before I can identify meaningful patterns."
        }

    prompt = f"""
You are LiAInne.

You are reviewing a user's journal analytics.

Statistics:

{stats}

Write:

1. One observation
2. One recommendation

Rules:
- Maximum 80 words.
- Sound personal and thoughtful.
- Do not list statistics.
- Do not mention slopes.
- Do not say 'based on the data'.
- Focus on patterns and actionable advice.
"""

    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "system", "content": prompt}],
        temperature=0.8,
        max_tokens=150,
    )

    return {"insight": response.choices[0].message.content}


@app.get("/monthly-review")
def monthly_review():
    context = build_monthly_review_context()

    if not context:
        return {"review": "Not enough journal entries this month yet."}

    # Enrich with quest/goal progress so the review mentions milestones
    goal_data = build_goal_summary()
    quest_summary = ""
    if goal_data:
        category_health = build_category_health(goal_data)
        total_xp = sum(g["xp"] for g in goal_data)
        completed_quests = sum(g["completed_tasks"] for g in goal_data)
        total_quests = sum(g["total_tasks"] for g in goal_data)
        best_cat = category_health[0]["category"] if category_health else None
        stale_cats = [c["category"] for c in category_health if c["stale"]]
        quest_summary = (
            f"Quest progress this month: {completed_quests}/{total_quests} quests complete, "
            f"{total_xp} total XP earned across {len(goal_data)} active goals. "
            f"Strongest category: {best_cat}. "
            + (f"Stalled categories: {', '.join(stale_cats)}." if stale_cats else "No stalled categories.")
        )

    prompt = f"""You are LiAInne.

Create a monthly review.

Journal statistics:
{context}

Quest and goal progress:
{quest_summary}

Write the review using exactly these sections:

## Wins

## Challenges

## Patterns

## Focus For Next Month

Rules:
- Maximum 300 words.
- Be encouraging but honest.
- Mention quest completions and any stalled goals by name if relevant.
- Give actionable focus areas.
- Do not dump statistics.
- Write in natural language.
"""

    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "system", "content": prompt}],
        temperature=0.7,
        max_tokens=500,
    )

    return {"review": response.choices[0].message.content}




# ---------------------------------------------------------------------------
# Skill Trees
#
# Architecture:
#   - Trees are defined as static JSON (per your v1 decision).
#   - Each node has: id, name, xp_required, prerequisites (list of node ids)
#   - XP feeding into nodes comes from completed goal tasks in the same
#     category. 50 XP per completed quest (XP_PER_TASK).
#   - A node is UNLOCKED when:
#       (a) all prerequisite nodes are completed, AND
#       (b) total category XP >= node.xp_required
#   - A node is COMPLETED when the user manually marks it done
#     (stored in Supabase: skill_progress table).
#   - GET /skills          → full tree + unlock status for every node
#   - POST /skills/{id}/complete  → mark a node complete
#   - DELETE /skills/{id}/complete → unmark (undo)
# ---------------------------------------------------------------------------

SKILL_TREES: dict[str, dict] = {
    "Study": {
        "label": "Computer Science",
        "icon": "📚",
        "color": "#6c8ebf",
        "nodes": [
            {
                "id": "cs_fundamentals",
                "name": "Programming Fundamentals",
                "xp_required": 0,
                "prerequisites": [],
                "description": "Variables, loops, functions, and basic problem solving.",
            },
            {
                "id": "cs_python",
                "name": "Python Basics",
                "xp_required": 100,
                "prerequisites": ["cs_fundamentals"],
                "description": "Syntax, data types, list comprehensions, modules.",
            },
            {
                "id": "cs_dsa",
                "name": "Data Structures",
                "xp_required": 200,
                "prerequisites": ["cs_fundamentals"],
                "description": "Arrays, linked lists, stacks, queues, hashmaps.",
            },
            {
                "id": "cs_algorithms",
                "name": "Algorithms",
                "xp_required": 400,
                "prerequisites": ["cs_dsa"],
                "description": "Sorting, searching, recursion, dynamic programming.",
            },
            {
                "id": "cs_oop",
                "name": "Object-Oriented Programming",
                "xp_required": 300,
                "prerequisites": ["cs_python"],
                "description": "Classes, inheritance, polymorphism, design patterns.",
            },
            {
                "id": "cs_web",
                "name": "Web Development",
                "xp_required": 350,
                "prerequisites": ["cs_oop"],
                "description": "APIs, HTTP, frontend basics, backend frameworks.",
            },
            {
                "id": "cs_ai",
                "name": "AI & Machine Learning",
                "xp_required": 600,
                "prerequisites": ["cs_algorithms", "cs_oop"],
                "description": "ML fundamentals, neural networks, model training.",
            },
            {
                "id": "cs_security",
                "name": "Cybersecurity",
                "xp_required": 500,
                "prerequisites": ["cs_web", "cs_algorithms"],
                "description": "Threats, encryption, auth, secure coding.",
            },
        ],
    },
    "Fitness": {
        "label": "Physical Mastery",
        "icon": "💪",
        "color": "#82b366",
        "nodes": [
            {
                "id": "fit_consistency",
                "name": "Consistency",
                "xp_required": 0,
                "prerequisites": [],
                "description": "Exercise at least 3x/week for 4 consecutive weeks.",
            },
            {
                "id": "fit_strength",
                "name": "Strength Foundation",
                "xp_required": 100,
                "prerequisites": ["fit_consistency"],
                "description": "Master compound lifts: squat, deadlift, press.",
            },
            {
                "id": "fit_cardio",
                "name": "Cardio Base",
                "xp_required": 100,
                "prerequisites": ["fit_consistency"],
                "description": "Run 5km without stopping.",
            },
            {
                "id": "fit_nutrition",
                "name": "Nutrition Basics",
                "xp_required": 150,
                "prerequisites": ["fit_consistency"],
                "description": "Track macros, meal prep, understand caloric balance.",
            },
            {
                "id": "fit_advanced",
                "name": "Advanced Training",
                "xp_required": 400,
                "prerequisites": ["fit_strength", "fit_cardio"],
                "description": "Periodization, progressive overload, recovery.",
            },
        ],
    },
    "Finance": {
        "label": "Financial Intelligence",
        "icon": "💰",
        "color": "#d6a73a",
        "nodes": [
            {
                "id": "fin_budgeting",
                "name": "Budgeting",
                "xp_required": 0,
                "prerequisites": [],
                "description": "Track income and expenses, build a monthly budget.",
            },
            {
                "id": "fin_emergency",
                "name": "Emergency Fund",
                "xp_required": 100,
                "prerequisites": ["fin_budgeting"],
                "description": "Save 3 months of expenses.",
            },
            {
                "id": "fin_debt",
                "name": "Debt Elimination",
                "xp_required": 150,
                "prerequisites": ["fin_budgeting"],
                "description": "Avalanche or snowball method to eliminate debt.",
            },
            {
                "id": "fin_investing",
                "name": "Investing Basics",
                "xp_required": 300,
                "prerequisites": ["fin_emergency"],
                "description": "Index funds, ETFs, compound interest, tax-advantaged accounts.",
            },
            {
                "id": "fin_income",
                "name": "Income Growth",
                "xp_required": 400,
                "prerequisites": ["fin_debt", "fin_investing"],
                "description": "Side income, salary negotiation, skill monetization.",
            },
        ],
    },
    "Creativity": {
        "label": "Creative Mastery",
        "icon": "🎨",
        "color": "#9c70c4",
        "nodes": [
            {
                "id": "cr_basics",
                "name": "Creative Foundations",
                "xp_required": 0,
                "prerequisites": [],
                "description": "Daily practice habit, overcoming blank-page paralysis.",
            },
            {
                "id": "cr_craft",
                "name": "Craft Fundamentals",
                "xp_required": 100,
                "prerequisites": ["cr_basics"],
                "description": "Core techniques for your chosen medium.",
            },
            {
                "id": "cr_voice",
                "name": "Personal Voice",
                "xp_required": 250,
                "prerequisites": ["cr_craft"],
                "description": "Develop a distinct style others can recognise.",
            },
            {
                "id": "cr_project",
                "name": "Finish a Project",
                "xp_required": 200,
                "prerequisites": ["cr_craft"],
                "description": "Complete one significant creative work end-to-end.",
            },
            {
                "id": "cr_share",
                "name": "Share Your Work",
                "xp_required": 350,
                "prerequisites": ["cr_voice", "cr_project"],
                "description": "Publish, perform, or exhibit. Feedback loop matters.",
            },
        ],
    },
    "Personal Growth": {
        "label": "Self Mastery",
        "icon": "🌱",
        "color": "#d07040",
        "nodes": [
            {
                "id": "pg_awareness",
                "name": "Self Awareness",
                "xp_required": 0,
                "prerequisites": [],
                "description": "Daily journaling, identify core values and blind spots.",
            },
            {
                "id": "pg_habits",
                "name": "Habit Architecture",
                "xp_required": 100,
                "prerequisites": ["pg_awareness"],
                "description": "Design habit stacks, track streaks, remove friction.",
            },
            {
                "id": "pg_mindset",
                "name": "Growth Mindset",
                "xp_required": 150,
                "prerequisites": ["pg_awareness"],
                "description": "Reframe failure, embrace discomfort, learn from feedback.",
            },
            {
                "id": "pg_focus",
                "name": "Deep Focus",
                "xp_required": 200,
                "prerequisites": ["pg_habits"],
                "description": "Deep work sessions, distraction elimination, flow state.",
            },
            {
                "id": "pg_leadership",
                "name": "Leadership",
                "xp_required": 500,
                "prerequisites": ["pg_mindset", "pg_focus"],
                "description": "Influence, communication, accountability to others.",
            },
        ],
    },
}


def get_category_xp(category: str) -> int:
    """Total XP earned in a category from completed quest tasks."""
    goal_data = build_goal_summary()
    return sum(
        g["xp"] for g in goal_data if g.get("category") == category
    )


def get_completed_node_ids(category: str) -> set[str]:
    """Fetch which skill nodes the user has manually completed."""
    result = (
        supabase.table("skill_progress")
        .select("node_id")
        .eq("category", category)
        .execute()
    )
    return {row["node_id"] for row in result.data}


def resolve_tree(category: str) -> dict:
    """
    Return the tree definition with unlock/completion status resolved
    for every node.
    """
    tree_def = SKILL_TREES.get(category)
    if not tree_def:
        return {}

    xp = get_category_xp(category)
    completed_ids = get_completed_node_ids(category)

    resolved_nodes = []
    for node in tree_def["nodes"]:
        prereqs_met = all(p in completed_ids for p in node["prerequisites"])
        xp_met = xp >= node["xp_required"]
        unlocked = prereqs_met and xp_met
        completed = node["id"] in completed_ids

        resolved_nodes.append(
            {
                **node,
                "unlocked": unlocked,
                "completed": completed,
                "prereqs_met": prereqs_met,
                "xp_met": xp_met,
                "category_xp": xp,
            }
        )

    return {
        **tree_def,
        "category": category,
        "category_xp": xp,
        "nodes": resolved_nodes,
    }


@app.get("/skills")
def get_skills():
    """All trees with unlock/completion status resolved."""
    return [resolve_tree(cat) for cat in SKILL_TREES]


@app.get("/skills/{category}")
def get_skill_tree(category: str):
    """Single tree for a given category."""
    tree = resolve_tree(category)
    if not tree:
        raise HTTPException(status_code=404, detail="Skill tree not found")
    return tree


@app.post("/skills/{node_id}/complete")
def complete_skill_node(node_id: str, category: str):
    """Mark a skill node as completed. Requires node to be unlocked."""
    tree = resolve_tree(category)
    if not tree:
        raise HTTPException(status_code=404, detail="Skill tree not found")

    node = next((n for n in tree["nodes"] if n["id"] == node_id), None)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    if not node["unlocked"]:
        raise HTTPException(status_code=403, detail="Node not yet unlocked")

    supabase.table("skill_progress").upsert(
        {
            "node_id": node_id,
            "category": category,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
    ).execute()

    return {"status": "completed", "node_id": node_id}


@app.delete("/skills/{node_id}/complete")
def uncomplete_skill_node(node_id: str, category: str):
    """Unmark a skill node (undo completion)."""
    supabase.table("skill_progress").delete().eq("node_id", node_id).execute()
    return {"status": "removed", "node_id": node_id}

app.mount("/", StaticFiles(directory="static", html=True), name="static")