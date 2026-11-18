"""Lossless logical backups. Restore and migration each use a single SQLite transaction."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from backend.journal_store import connection
from backend.sqlite_schema import SCHEMA, decode, encode, initialize, physical, pk, quote

BACKUP_DIR = Path(__file__).resolve().parents[1] / "backup"


def dump(conn):
    tables = {t:[decode(t,row) for row in conn.execute(f"SELECT * FROM {physical(t)} ORDER BY {quote(pk(t))}")]
              for t in SCHEMA}
    return {"format":"liainne-local-v1", "timestamp":datetime.now(timezone.utc).isoformat(),
            "counts":{t:len(rows) for t,rows in tables.items()}, "tables":tables}


def save_snapshot(document, label):
    BACKUP_DIR.mkdir(mode=0o700, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = BACKUP_DIR / f"{label}-{stamp}.json"
    with os.fdopen(os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600),"w") as out:
        json.dump(document,out,ensure_ascii=False)
    return target


def validate(doc):
    if doc.get("format") not in ("liainne-local-v1","liainne-supabase-v1"):
        raise ValueError("Unsupported backup format")
    if set(doc["tables"]) != set(SCHEMA) or set(doc["counts"]) != set(SCHEMA):
        raise ValueError("Backup table inventory differs from the audited schema")
    for table,rows in doc["tables"].items():
        if not isinstance(rows,list) or len(rows)!=doc["counts"][table]:
            raise ValueError(f"Count mismatch in {table}")
        if any(set(row)!=set(SCHEMA[table]) for row in rows):
            raise ValueError(f"Column mismatch in {table}")
        keys = [row[pk(table)] for row in rows]
        if None in keys or len(set(keys))!=len(keys):
            raise ValueError(f"Invalid primary keys in {table}")
    if doc.get("buckets") or doc.get("files"):
        raise ValueError("Backup contains Storage objects. Preserve the original export before extending the restore schema.")


def restore(doc, *, replace=False, snapshot=True):
    validate(doc)
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        initialize(conn)
        conn.execute("PRAGMA defer_foreign_keys=ON")
        original = dump(conn)
        recovery = save_snapshot(original,"before-restore") if snapshot else None
        # Defer all FK checks until the complete dataset has been inserted.
        if replace:
            for table in SCHEMA:
                conn.execute(f"DELETE FROM {physical(table)}")
        expected = {}
        for table,rows in doc["tables"].items():
            key = pk(table)
            existing = {} if replace else {r[key]:r for r in original["tables"][table]}
            for row in rows:
                if row[key] in existing:
                    if row != existing[row[key]]:
                        raise ValueError(f"Conflicting {table} primary key. No changes committed.")
                    continue
                cols = list(row)
                conn.execute(f"INSERT INTO {physical(table)} ({','.join(map(quote,cols))}) VALUES ({','.join('?' for _ in cols)})",
                             [encode(table,k,row[k]) for k in cols])
                existing[row[key]]=row
            expected[table]=existing
        actual = dump(conn)
        for table,rows in actual["tables"].items():
            if {r[pk(table)]:r for r in rows} != expected[table]:
                raise ValueError(f"Record verification failed in {table}")
        if conn.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("Foreign-key verification failed")
        return {"counts":actual["counts"],"before_restore":recovery.name if recovery else None}

