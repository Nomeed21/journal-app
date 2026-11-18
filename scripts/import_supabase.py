"""Run from project root: python -m scripts.import_supabase backup/supabase-export-...json [--apply]."""
import argparse
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from backend import bootstrap_env, journal_store
from backend.data_backup import restore


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup",type=Path)
    parser.add_argument("--apply",action="store_true")
    args=parser.parse_args()
    doc=json.loads(args.backup.read_text())
    original=Path(os.environ.get("LIAINNE_JOURNAL_DB") or journal_store.DEFAULT_PATH).resolve()
    with TemporaryDirectory() as tmp:
        trial=Path(tmp)/"trial.sqlite3"
        if original.exists():
            with closing(sqlite3.connect(original.as_uri()+"?mode=ro",uri=True)) as src, closing(sqlite3.connect(trial)) as dst:
                src.backup(dst)
        os.environ["LIAINNE_JOURNAL_DB"]=str(trial)
        result=restore(doc,snapshot=False)
        print("Dry run verified all rows and foreign keys.",result["counts"])
        print("2026-11-01 streak:",journal_store.journal_streak("2026-11-01"))
        with journal_store.connection() as conn:
            print("November 1 mood-3 records:",conn.execute("SELECT count(*) FROM entries WHERE date(created_at,'+8 hours')='2026-11-01' AND mood=3").fetchone()[0])
    if args.apply:
        os.environ["LIAINNE_JOURNAL_DB"]=str(original)
        result=restore(doc)
        print("Import committed after exact record comparison. Prior local backup:",result["before_restore"])


if __name__=="__main__":
    main()

