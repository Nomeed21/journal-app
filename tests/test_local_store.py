import os
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from backend import journal_store
from backend.data_backup import dump, restore
from backend.sqlite_schema import initialize
from backend.local_store import Query


class SQLiteCompatibility(unittest.TestCase):
    def setUp(self):
        folder = self.enterContext(TemporaryDirectory())
        self.enterContext(patch.dict(os.environ, {"LIAINNE_JOURNAL_DB":str(Path(folder)/"test.sqlite3")}))
        with journal_store.connection() as conn:
            initialize(conn)

    def test_relations_filters_defaults_and_upsert(self):
        goal=Query("goals").insert({"title":"Practice","category":"Study"}).execute().data[0]
        task=Query("goal_tasks").insert({"goal_id":goal["id"],"title":"Read"}).execute().data[0]
        self.assertIs(task["is_completed"], False)
        self.assertTrue(goal["created_at"])
        self.assertEqual(Query("goal_tasks").select("id").in_("goal_id",[goal["id"]]).is_("quest_id","null").single().execute().data, {"id":task["id"]})
        self.assertFalse(Query("goal_tasks").select().not_.is_("quest_id","null").execute().data)
        row={"source_type":"task","source_id":"1","category":"Study","xp":2}
        Query("xp_ledger").upsert(row,on_conflict="source_type,source_id").execute()
        Query("xp_ledger").upsert({**row,"xp":3},on_conflict="source_type,source_id").execute()
        self.assertEqual(Query("xp_ledger").select("xp").gte("xp",3).order("id").range(0,0).execute().data,[{"xp":3}])
        Query("goals").delete().eq("id",goal["id"]).execute()
        self.assertEqual(Query("goal_tasks").select().execute().data,[])

    def test_restore_round_trip_and_rollback(self):
        journal_store.save({"content":"Synthetic","entry_type":"free","tags":["quiet"],"created_at":"2026-11-01T00:00:00Z"})
        with journal_store.connection() as conn:
            before=dump(conn)
        self.assertEqual(restore(before,replace=True,snapshot=False)["counts"]["journal_entries"],1)
        broken={**before,"tables":{**before["tables"],"goal_tasks":[dict(id=1,title="x",goal_id=999,quest_id=None,is_completed=False,created_at=None)]},
                "counts":{**before["counts"],"goal_tasks":1}}
        with self.assertRaises((ValueError,sqlite3.IntegrityError)):
            restore(broken,replace=True,snapshot=False)
        with journal_store.connection() as conn:
            self.assertEqual(dump(conn)["tables"], before["tables"])

