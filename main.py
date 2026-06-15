import os
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer
from supabase import create_client
from groq import Groq

from collections import defaultdict
from datetime import timedelta

# Load environment variables from .env
load_dotenv()

# Global variable for the embedding model (loaded during startup)
embedding_model = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load the embedding model once when the app starts
    global embedding_model
    embedding_model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    yield


# Create the FastAPI app with a lifespan handler
app = FastAPI(lifespan=lifespan)

# Initialize Supabase and Groq clients using env vars
supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])


# Define the shape of data for creating a journal entry
class EntryCreate(BaseModel):
    title: str
    content: str
    mood: int
    goal_progress: int


# Define the shape of data for chat messages
class ChatMessage(BaseModel):
    message: str

class HabitLog(BaseModel):
    name: str

def generate_embedding(text: str) -> list[float]:
    # Encode the text into a 384-dimensional vector
    embedding = embedding_model.encode(text)
    return embedding.tolist()

@app.post("/entries")
def create_entry(entry: EntryCreate):
    # Combine all fields into a single string for richer embeddings
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
    }

    result = supabase.table("journal_entries").insert(data).execute()
    return {"status": "created", "entry": result.data[0]}



@app.get("/entries")
def get_entries():
    # Fetch all entries, newest first, excluding the embedding column
    result = (
        supabase.table("journal_entries")
        .select("id, title, content, mood, goal_progress, created_at")
        .order("created_at", desc=True)
        .execute()
    )
    return result.data


@app.get("/entries/{entry_id}")
def get_entry(entry_id: int):
    # Fetch a single entry by its ID
    result = (
        supabase.table("journal_entries")
        .select("id, title, content, mood, goal_progress, created_at")
        .eq("id", entry_id)
        .single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Entry not found")
    return result.data

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

    streaks = {}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for name, dates in habit_dates.items():
        unique_dates = sorted(set(dates), reverse=True)
        streak = 0
        expected = datetime.strptime(today, "%Y-%m-%d")
        for date_str in unique_dates:
            date = datetime.strptime(date_str, "%Y-%m-%d")
            if date == expected or date == expected - timedelta(days=1):
                streak += 1
                expected = date - timedelta(days=1)
            else:
                break
        streaks[name] = {"current_streak": streak, "total_logs": len(dates)}

    return streaks

@app.post("/chat")
def chat(msg: ChatMessage):
    # Convert the user's message into a vector embedding
    query_embedding = generate_embedding(msg.message)
        # Call the Supabase RPC function to find similar entries
    similar_entries = supabase.rpc(
        "match_entries",
        {
            "query_embedding": query_embedding,
            "match_threshold": 0.3,
            "match_count": 5,
        },
    ).execute()

    # Format each matching entry into a readable context string
    context_parts = []
    for entry in similar_entries.data:
        context_parts.append(
            f"[{entry['created_at'][:10]}] "
            f"(Mood: {entry['mood']}/5, Goal: {entry['goal_progress']}%) "
            f"{entry['title']}: {entry['content']}"
        )

    context = "\n\n".join(context_parts) if context_parts else "No journal entries found yet."
        # Define the chatbot's personality and rules
    system_prompt = (
        "Your name is LiAInne. You are a direct, honest accountability partner — "
        "the friend who gives real feedback, not empty validation. "
        "You have access to the user's journal entries, including mood (1-5) and "
        "goal progress (0-100%).\n\n"
        "Rules:\n"
        "- Compare goal_progress and mood across dates to identify real trends before commenting.\n"
        "- If progress is flat or declining despite claims of effort, point it out directly but constructively — "
        "focus on the gap between intention and outcome, not on judging the person.\n"
        "- If they ARE improving, celebrate it with specifics (cite dates and numbers).\n"
        "- Avoid generic encouragement ('keep going!') — always back feedback with data from their entries.\n"
        "- Reference specific entries by date when making a point.\n"
        "- If mood is consistently low (e.g. 3+ days at 1-2/5), don't ignore it or dismiss it, but also don't diagnose "
        "or give clinical advice. Gently note the pattern, ask what might be contributing, and encourage them to talk "
        "to a trusted person or professional if it continues — frame this as one option, not a deflection.\n"
        "- Stay constructive: 'tough but fair,' never harsh, sarcastic, or shaming.\n"
        "- Keep responses concise and actionable — 2-4 sentences unless more detail is asked for.\n\n"
        f"Relevant journal entries:\n{context}"
    )
    
    streaks_result = (
    supabase.table("habits")
    .select("name, completed_at")
    .order("completed_at", desc=True)
    .limit(50)
    .execute()
    )

    habit_dates = defaultdict(list)
    for row in streaks_result.data:
        habit_dates[row["name"]].append(row["completed_at"])

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    habit_summary_parts = []
    for name, dates in habit_dates.items():
        unique_dates = sorted(set(dates), reverse=True)
        streak = 0
        expected = datetime.strptime(today, "%Y-%m-%d")
        for date_str in unique_dates:
            date = datetime.strptime(date_str, "%Y-%m-%d")
            if date == expected or date == expected - timedelta(days=1):
                streak += 1
                expected = date - timedelta(days=1)
            else:
                break
        last_done = unique_dates[0] if unique_dates else "never"
        habit_summary_parts.append(f"- {name}: {streak}-day streak, last done {last_done}")

    habit_context = "\n".join(habit_summary_parts) if habit_summary_parts else "No habits tracked yet."
    system_prompt += f"\n\nHabit tracker data:\n{habit_context}"
    # Send the prompt and user message to Groq's LLM
    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": msg.message},
        ],
        temperature=1,
        max_tokens=1024,
    )

    return {"response": response.choices[0].message.content}

app.mount("/", StaticFiles(directory="static", html=True), name="static")


