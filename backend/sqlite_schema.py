"""Schema metadata for the 31 audited LiAInne tables."""
import json
from pathlib import Path

SCHEMA = json.loads(Path(__file__).with_name("local_schema.json").read_text())
UNIQUE = {"xp_ledger": ("source_type","source_id"), "vp_ledger": ("source_type","source_id"),
          "skill_progress": ("node_id",), "daily_plans": ("plan_date",), "coach_patterns": ("pattern_key",),
          "habit_profiles": ("name",), "weekly_bosses": ("week_key",), "monthly_reviews": ("month_key",),
          "routine_logs": ("category_id","log_date")}


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def physical(table):
    return quote("entries" if table == "journal_entries" else table)


def pk(table):
    return next(k for k,c in SCHEMA[table].items() if c.get("pk"))


def encode(table, key, value):
    if value is not None and SCHEMA[table][key]["type"] in ("jsonb","text[]"):
        return json.dumps(value, ensure_ascii=False)
    return value


def decode(table, row):
    output = dict(row)
    for key,value in output.items():
        kind = SCHEMA[table][key]["type"]
        if value is not None and kind in ("jsonb","text[]"):
            output[key] = json.loads(value)
        elif value is not None and kind == "boolean":
            output[key] = bool(value)
    return output


def column_sql(key, info, table):
    kind = info["type"]
    sqltype = {"boolean":"INTEGER","integer":"INTEGER","bigint":"INTEGER","numeric":"NUMERIC"}.get(kind,"TEXT")
    result = quote(key) + " " + sqltype
    if info.get("pk"):
        result += " PRIMARY KEY" + (" AUTOINCREMENT" if sqltype == "INTEGER" else "")
    elif info.get("required"):
        result += " NOT NULL"
    if "default" in info:
        default = info["default"]
        if default == "now()":
            result += " DEFAULT (strftime('%Y-%m-%dT%H:%M:%f+00:00','now'))"
        elif default == "CURRENT_DATE":
            result += " DEFAULT CURRENT_DATE"
        elif isinstance(default,(float,int)):
            result += f" DEFAULT {int(default) if isinstance(default,bool) else default}"
        else:
            result += " DEFAULT '" + str(default).replace("'","''") + "'"
    if info.get("references"):
        parent,field = info["references"]
        action = "SET NULL" if key in ("parent_quest_id","milestone_id") or table in ("board_quests","focus_sessions") else "CASCADE"
        result += f" REFERENCES {physical(parent)}({quote(field)}) ON DELETE {action}"
    return result


def initialize(conn):
    for table,columns in SCHEMA.items():
        definitions = {k:column_sql(k,v,table) for k,v in columns.items()}
        if table == "journal_entries":
            existing = {r[1] for r in conn.execute("PRAGMA table_info(entries)")}
            for key in definitions.keys() - existing:
                conn.execute("ALTER TABLE entries ADD COLUMN " + definitions[key])
        else:
            conn.execute(f"CREATE TABLE IF NOT EXISTS {physical(table)} ({','.join(definitions.values())})")
        if table in UNIQUE:
            keys = ",".join(map(quote,UNIQUE[table]))
            conn.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS uq_{table} ON {physical(table)} ({keys})")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_board_source ON board_quests(source_type,source_id) WHERE source_id <> ''")

