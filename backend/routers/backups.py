"""User-initiated backup and restore for the single-user local server."""
import os
import sqlite3
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from backend import journal_store
from backend.data_backup import dump, restore

router = APIRouter(prefix="/settings")


def require_local_mode():
    if os.getenv("LIAINNE_DATA_BACKEND", "sqlite") != "sqlite":
        raise HTTPException(409, "Switch to SQLite mode before exporting or restoring local data.")


@router.get("/backup")
def export_backup():
    require_local_mode()
    with journal_store.connection() as conn:
        conn.execute("BEGIN")
        document = dump(conn)
    return JSONResponse(document, headers={"Cache-Control":"no-store"})


@router.post("/restore")
def import_backup(document: dict):
    require_local_mode()
    if document.get("format") != "liainne-local-v1":
        raise HTTPException(422,"Choose a LiAInne Settings backup.")
    try:
        result = restore(document, replace=True)
    except (ValueError, TypeError, KeyError, sqlite3.IntegrityError) as exc:
        raise HTTPException(422, "Invalid or inconsistent backup. Your data was kept.") from exc
    from backend import main
    main._invalidate_habit_dates_cache()
    main._invalidate_board_cache()
    main._invalidate_total_xp_cache()
    main._invalidate_domain_level_cache()
    return result

