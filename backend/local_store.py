"""SQLite query operations used by the current FastAPI callers."""
from types import SimpleNamespace
from backend.sqlite_schema import SCHEMA, quote, physical, encode, decode, pk
from backend.journal_store import connection


class Query:
    def __init__(self, table, connect=connection):
        self.table, self.connect = table, connect
        self.schema = SCHEMA[table]
        self.fields, self.action = "*", "select"
        self.filters, self.args, self.sort = [], [], []
        self.size, self.offset = None, 0
        self.one, self.negated = False, False
        self.payload, self.conflict = None, None

    def column(self, name):
        if name not in self.schema:
            raise ValueError(f"Unknown {self.table} column: {name}")
        return quote(name)

    def select(self, fields="*"):
        self.fields = "*" if fields == "*" else ",".join(self.column(k.strip()) for k in fields.split(","))
        return self

    def _filter(self, key, op, value):
        self.filters.append(self.column(key) + " " + op + " ?")
        self.args.append(value)
        return self

    def eq(self, k, v): return self._filter(k, "=", v)
    def gte(self, k, v): return self._filter(k, ">=", v)
    def lte(self, k, v): return self._filter(k, "<=", v)
    def lt(self, k, v): return self._filter(k, "<", v)
    def like(self, k, v): return self._filter(k, "LIKE", v)

    @property
    def not_(self):
        self.negated = True
        return self

    def is_(self, k, v):
        op = "IS NOT" if self.negated else "IS"
        self.negated = False
        return self._filter(k, op, None if v == "null" else v)

    def in_(self, k, values):
        self.filters.append(self.column(k) + " IN (" + ",".join("?" for _ in values) + ")")
        self.args.extend(values)
        return self

    def order(self, k, desc=False):
        self.sort.append(self.column(k) + (" DESC" if desc else " ASC"))
        return self

    def single(self):
        self.one = True
        return self

    def limit(self, size):
        self.size = size
        return self

    def range(self, start, end):
        self.offset, self.size = start, end-start+1
        return self

    def insert(self, data):
        self.action, self.payload = "insert", data
        return self

    def upsert(self, data, on_conflict=None):
        self.insert(data)
        self.conflict = (on_conflict or pk(self.table)).split(",")
        return self

    def update(self, data):
        self.action, self.payload = "update", data
        return self

    def delete(self):
        self.action = "delete"
        return self

    def _insert(self, conn, row):
        cols = [self.column(k) for k in row]
        sql = f"INSERT INTO {physical(self.table)} ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})"
        if self.conflict:
            keys = [self.column(k.strip()) for k in self.conflict]
            updates = [c+"=excluded."+c for c in cols if c not in keys]
            sql += " ON CONFLICT (" + ",".join(keys) + ") DO "
            sql += "UPDATE SET " + ",".join(updates) if updates else "NOTHING"
        return conn.execute(sql+" RETURNING *",[encode(self.table,k,v) for k,v in row.items()]).fetchall()

    def execute(self):
        table = physical(self.table)
        where = " WHERE " + " AND ".join(self.filters) if self.filters else ""
        with self.connect() as conn:
            if self.action == "insert":
                rows = []
                for row in self.payload if isinstance(self.payload,list) else [self.payload]:
                    rows.extend(self._insert(conn,row))
            elif self.action == "update":
                sets = ",".join(self.column(k)+"=?" for k in self.payload)
                values = [encode(self.table,k,v) for k,v in self.payload.items()]
                rows = conn.execute(f"UPDATE {table} SET {sets}{where} RETURNING *",values+self.args).fetchall()
            elif self.action == "delete":
                rows = conn.execute(f"DELETE FROM {table}{where} RETURNING *",self.args).fetchall()
            else:
                sql = f"SELECT {self.fields} FROM {table}{where}"
                if self.sort:
                    sql += " ORDER BY " + ",".join(self.sort)
                args = list(self.args)
                if self.size is not None:
                    sql += " LIMIT ? OFFSET ?"
                    args.extend([self.size,self.offset])
                rows = conn.execute(sql,args).fetchall()
        data = [decode(self.table,r) for r in rows]
        if self.one and len(data)>1:
            raise ValueError("Expected a single row")
        return SimpleNamespace(data=(data[0] if data else None) if self.one else data)

