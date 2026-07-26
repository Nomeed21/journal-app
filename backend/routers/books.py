"""Reading-list API routes."""
from datetime import datetime, timezone
from typing import Callable, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.db import supabase

router = APIRouter()
_ledger_add: Callable | None = None
_award_achievements: Callable | None = None


def configure(*, ledger_add: Callable, award_achievements: Callable) -> None:
    """Supply cross-feature services without importing the application module."""
    global _ledger_add, _award_achievements
    _ledger_add = ledger_add
    _award_achievements = award_achievements


# Reading List — lives inside the Quest Board page. Three states:
# want_to_read -> reading -> finished. Starting and finishing a book both
# grant XP into Personal Growth via the same xp_ledger everything else in
# this app uses, so a book you actually read shows up in your level/XP the
# same way a quest or habit does.
#
# Requires a `books` table with columns: id, title, author, total_pages,
# current_page, status, summary, reflection, started_at, finished_at,
# created_at.
# ---------------------------------------------------------------------------

BOOK_START_XP  = 20   # starting a book is a small nudge of XP -- follow-through matters more
BOOK_FINISH_XP = 100  # finishing (with summary + reflection) is the real payoff

class BookCreate(BaseModel):
    title: str
    author: str = ""
    total_pages: Optional[int] = None

class BookUpdate(BaseModel):
    title: Optional[str] = None
    author: Optional[str] = None
    total_pages: Optional[int] = None

class BookProgressUpdate(BaseModel):
    current_page: int

class BookFinish(BaseModel):
    summary: str = ""
    reflection: str = ""

@router.get("/books")
def get_books():
    try:
        rows = supabase.table("books").select("*").order("created_at", desc=True).execute().data
    except Exception:
        rows = []
    return {
        "reading":      [b for b in rows if b.get("status") == "reading"],
        "want_to_read": [b for b in rows if b.get("status") == "want_to_read"],
        "finished":     sorted((b for b in rows if b.get("status") == "finished"),
                                key=lambda b: b.get("finished_at") or "", reverse=True),
    }

@router.post("/books")
def create_book(book: BookCreate):
    row = supabase.table("books").insert({
        "title":        book.title.strip() or "Untitled",
        "author":       book.author.strip(),
        "total_pages":  book.total_pages,
        "current_page": 0,
        "status":       "want_to_read",
        "summary":      "",
        "reflection":   "",
        "created_at":   datetime.now(timezone.utc).isoformat(),
    }).execute()
    return {"status": "created", "book": row.data[0]}

@router.put("/books/{book_id}")
def update_book(book_id: int, book: BookUpdate):
    update = {k: v for k, v in book.dict().items() if v is not None}
    if not update:
        raise HTTPException(400, "Nothing to update")
    result = supabase.table("books").update(update).eq("id", book_id).execute()
    if not result.data:
        raise HTTPException(404, "Book not found")
    return {"status": "updated", "book": result.data[0]}

@router.post("/books/{book_id}/start")
def start_book(book_id: int):
    """Move a book from Want to Read -> Currently Reading. Idempotent —
    an already-started book is returned unchanged rather than re-granting
    XP or overwriting started_at (ledger_add's own upsert-by-source-id
    would no-op the XP anyway, but this keeps the response honest)."""
    book = supabase.table("books").select("*").eq("id", book_id).single().execute().data
    if not book:
        raise HTTPException(404, "Book not found")
    if book.get("status") == "reading":
        return {"status": "already_reading", "book": book, "xp_earned": 0}
    updated = supabase.table("books").update({
        "status":     "reading",
        "started_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", book_id).execute().data[0]
    boosted_xp = _ledger_add("book_started", str(book_id), "Personal Growth", BOOK_START_XP)
    new_achievements = _award_achievements()
    return {"status": "started", "book": updated, "xp_earned": boosted_xp, "new_achievements": new_achievements}

@router.put("/books/{book_id}/progress")
def update_book_progress(book_id: int, progress: BookProgressUpdate):
    book = supabase.table("books").select("*").eq("id", book_id).single().execute().data
    if not book:
        raise HTTPException(404, "Book not found")
    page = max(0, progress.current_page)
    if book.get("total_pages"):
        page = min(page, book["total_pages"])
    updated = supabase.table("books").update({"current_page": page}).eq("id", book_id).execute().data[0]
    return {"status": "updated", "book": updated}

@router.post("/books/{book_id}/finish")
def finish_book(book_id: int, data: BookFinish):
    """Marks a book finished with a summary + reflection, grants XP.
    Idempotent per book — re-finishing an already-finished book (e.g.
    editing the summary later) just updates the text without granting XP
    again, since ledger_add upserts by source_id."""
    book = supabase.table("books").select("*").eq("id", book_id).single().execute().data
    if not book:
        raise HTTPException(404, "Book not found")
    was_finished = book.get("status") == "finished"
    update_data = {
        "status":     "finished",
        "summary":    data.summary,
        "reflection": data.reflection,
    }
    if not was_finished:
        update_data["finished_at"] = datetime.now(timezone.utc).isoformat()
        if book.get("total_pages"):
            update_data["current_page"] = book["total_pages"]
    updated = supabase.table("books").update(update_data).eq("id", book_id).execute().data[0]

    boosted_xp, new_achievements = 0, []
    if not was_finished:
        boosted_xp = _ledger_add("book_finished", str(book_id), "Personal Growth", BOOK_FINISH_XP)
        new_achievements = _award_achievements()
    return {"status": "finished", "book": updated, "xp_earned": boosted_xp, "new_achievements": new_achievements}

@router.delete("/books/{book_id}")
def delete_book(book_id: int):
    result = supabase.table("books").delete().eq("id", book_id).execute()
    if not result.data:
        raise HTTPException(404, "Book not found")
    return {"status": "deleted"}

# ---------------------------------------------------------------------------
