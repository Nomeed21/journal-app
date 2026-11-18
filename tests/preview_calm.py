"""Optional synthetic preview: python tests/preview_calm.py (never uses Supabase)."""
import os
import sys
from tempfile import TemporaryDirectory
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_calm import db, main
from datetime import datetime, timedelta, timezone
import uvicorn
old=(datetime.now(timezone.utc)-timedelta(days=14)).isoformat()
folder = TemporaryDirectory()
os.environ["LIAINNE_JOURNAL_DB"] = str(Path(folder.name) / "preview.sqlite3")
main.journal_store.save({'title':'A quiet afternoon','content':'Synthetic preview: sat by the window with a book.','created_at':old,'mood':None,'tags':[],'entry_type':'free'})
db.rows['board_quests']=[{'id':1,'title':'Read a chapter','section':'weekly','due_date':old[:10],'created_at':old,'is_completed':False}]
uvicorn.run(main.app,host='127.0.0.1',port=8765)
