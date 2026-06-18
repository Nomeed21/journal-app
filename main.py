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


class ChatTurn(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class ChatMessage(BaseModel):
    message: str
    history: list[ChatTurn] = []  # prior turns this session, sent back by the client


class HabitLog(BaseModel):
    name: str


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


def linear_slope(values: list[float]) -> float:
    """Simple least-squares slope of values against their index (0,1,2...).
    Positive = trending up, negative = trending down, ~0 = flat."""
    n = len(values)
    if n < 2:
        return 0.0
    x_mean = (n - 1) / 2
    y_mean = sum(values) / n
    numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    if denominator == 0:
        return 0.0
    return numerator / denominator


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
        f"Mood: {entry.mood}/5. "
        f"Goal progress: {entry.goal_progress}%."
    )
    embedding = generate_embedding(combined_text)

    data = {
        "title": entry.title,
        "content": entry.content,
        "mood": entry.mood,
        "goal_progress": entry.goal_progress,
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
        "id, title, content, mood, goal_progress, tags, created_at"
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
        .select("mood, goal_progress, created_at")
        .gte("created_at", start)
        .order("created_at")
        .execute()
    )

    daily = {}
    for entry in result.data:
        date = entry["created_at"][:10]
        if date not in daily:
            daily[date] = {"moods": [], "goals": []}
        daily[date]["moods"].append(entry["mood"])
        daily[date]["goals"].append(entry["goal_progress"])

    trends = []
    for date, values in sorted(daily.items()):
        trends.append({
            "date": date,
            "avg_mood": round(sum(values["moods"]) / len(values["moods"]), 1),
            "avg_goal": round(sum(values["goals"]) / len(values["goals"]), 1),
        })

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
            correlations.append({
                "day": name,
                "avg_mood": round(sum(days[i]["moods"]) / len(days[i]["moods"]), 1),
                "avg_goal": round(sum(days[i]["goals"]) / len(days[i]["goals"]), 1),
            })
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
        f"Mood: {entry.mood}/5. "
        f"Goal progress: {entry.goal_progress}%."
    )
    embedding = generate_embedding(combined_text)

    data = {
        "title": entry.title,
        "content": entry.content,
        "mood": entry.mood,
        "goal_progress": entry.goal_progress,
        "tags": entry.tags,
        "embedding": embedding,
    }

    result = (
        supabase.table("journal_entries")
        .update(data)
        .eq("id", entry_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Entry not found")
    return {"status": "updated", "entry": result.data[0]}


@app.delete("/entries/{entry_id}")
def delete_entry(entry_id: int):
    result = (
        supabase.table("journal_entries")
        .delete()
        .eq("id", entry_id)
        .execute()
    )
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
    """Fetch mood/goal/date for every entry (cheap columns only) for trend math."""
    result = (
        supabase.table("journal_entries")
        .select("id, mood, goal_progress, created_at")
        .order("created_at")
        .execute()
    )
    return result.data


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
        parts.append(
            f"[{e['created_at'][:10]}] (Mood: {e['mood']}/5, Goal: {e['goal_progress']}%){tags} "
            f"{e['title']}: {e['content']}"
        )
    return "\n\n".join(parts)


def build_weekly_summary_block(all_light_entries: list[dict]) -> str:
    """Collapse everything older than RECENT_DAYS into weekly avg stats."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS))
    older = [
        e for e in all_light_entries
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
        rows.append(f"{key}: avg mood {avg_mood}/5, avg goal {avg_goal}%, {v['count']} entries")

    # If history is very long, keep it bounded: earliest rows + most recent
    # rows, with a note in between, rather than truncating silently.
    if len(rows) > MAX_WEEKLY_SUMMARY_ROWS:
        head = rows[: MAX_WEEKLY_SUMMARY_ROWS // 2]
        tail = rows[-(MAX_WEEKLY_SUMMARY_ROWS // 2):]
        omitted = len(rows) - len(head) - len(tail)
        rows = head + [f"... ({omitted} earlier weeks omitted, available via search) ..."] + tail

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
        lines.append(f"- {name}: {streak}-day streak, {len(dates)} total logs, last done {last_done}")
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
        e["id"] for e in all_light
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
        sections.append(f"SPECIFIC OLDER ENTRIES RELEVANT TO THIS QUESTION:\n{semantic_matches}")

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
        best_day = max(
            valid_days,
            key=lambda d: d["avg_mood"]
        )

    streaks = get_streaks()

    strongest_habit = None
    longest_streak = 0

    if streaks:
        strongest_habit, stats = max(
            streaks.items(),
            key=lambda item: item[1]["current_streak"]
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
                    "message": "Keep journaling. More entries are needed before meaningful patterns can be detected."
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
        insights.append({
            "type": "success",
            "title": "Mood Trend",
            "message": "Your mood has been improving over time.",
            "recommendation": "Review your recent entries and identify what has been helping."
        })
    elif mood_slope < -0.05:
        insights.append({
            "type": "warning",
            "title": "Mood Trend",
            "message": "Your mood has been gradually declining.",
            "recommendation": "Review your last few entries and look for recurring stressors."
        })

    # ---------------------------------------
    # Goal Trend
    # ---------------------------------------
    goals = [e["goal_progress"] for e in all_light]
    goal_slope = linear_slope(goals)

    if goal_slope > 0.5:
        insights.append({
            "type": "success",
            "title": "Goal Progress",
            "message": "Your goal progress is trending upward.",
            "recommendation": "Keep the current pace and focus on consistency."
        })
    elif goal_slope < -0.5:
        insights.append({
            "type": "warning",
            "title": "Goal Progress",
            "message": "Goal progress has slowed recently.",
            "recommendation": "Break your goals into smaller daily actions."
        })

    # ---------------------------------------
    # Best Day
    # ---------------------------------------
    correlations = get_correlations()

    valid_days = [d for d in correlations if d["avg_mood"] > 0]

    if valid_days:
        best_day = max(valid_days, key=lambda d: d["avg_mood"])

        insights.append({
            "type": "observation",
            "title": "Best Day",
            "message": f"{best_day['day']} is your strongest day with an average mood of {best_day['avg_mood']}/5.",
            "recommendation": f"Schedule important work on {best_day['day']} whenever possible."
        })

    # ---------------------------------------
    # Habits
    # ---------------------------------------
    streaks = get_streaks()

    if streaks:
        best_habit = max(
            streaks.items(),
            key=lambda item: item[1]["current_streak"]
        )

        habit_name = best_habit[0]
        streak = best_habit[1]["current_streak"]

        if streak >= 3:
            insights.append({
                "type": "success",
                "title": "Strong Habit",
                "message": f"'{habit_name}' currently has a {streak}-day streak.",
                "recommendation": "Protect this habit. It is becoming part of your identity."
            })

    if not insights:
        insights.append({
            "type": "info",
            "title": "No Strong Patterns Yet",
            "message": "No significant trends detected.",
            "recommendation": "Keep journaling consistently."
        })

    return {
        "insights": insights
    }

@app.get("/ai-insight")
def ai_insight():
    stats = build_ai_insight_context()

    if not stats:
        return {
            "insight":
                "Keep journaling. I need a little more data before I can identify meaningful patterns."
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
        messages=[
            {
                "role": "system",
                "content": prompt
            }
        ],
        temperature=0.8,
        max_tokens=150,
    )

    return {
        "insight": response.choices[0].message.content
    }


app.mount("/", StaticFiles(directory="static", html=True), name="static")
