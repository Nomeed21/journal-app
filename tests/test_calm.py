"""Synthetic tests only. Replace the database module before importing the app."""
from tempfile import TemporaryDirectory
from pathlib import Path
import os
import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

os.environ.pop("GROQ_API_KEY", None)
os.environ["LLM_PROVIDER"] = "groq"

class Database:
    def __init__(self):
        self.rows = {"journal_entries": [], "board_quests": []}
        self.writes = []
    def table(self, name):
        return Query(self, name)

class Query:
    def __init__(self, db, name):
        self.db, self.name, self.filters = db, name, []
        self.action, self.data, self.bounds = None, None, None
    def select(self, *args, **kwargs): return self
    def order(self, *args, **kwargs): return self
    def eq(self, key, value): self.filters.append((key, value)); return self
    def range(self, start, end): self.bounds=(start,end); return self
    def insert(self, data): self.action='insert'; self.data=data; return self
    def update(self, data): self.action='update'; self.data=data; return self
    def execute(self):
        rows=self.db.rows.setdefault(self.name, [])
        chosen=[r for r in rows if all(r.get(k)==v for k,v in self.filters)]
        if self.action:
            self.db.writes.append((self.name,self.action,self.data.copy()))
            if self.action=='insert':
                row={"id":len(rows)+1,**self.data}; rows.append(row); chosen=[row]
            else:
                for row in chosen: row.update(self.data)
        if self.bounds: chosen=chosen[self.bounds[0]:self.bounds[1]+1]
        return SimpleNamespace(data=[r.copy() for r in chosen])

db=Database()
module=ModuleType('backend.db'); module.supabase=db; module.db_retry=lambda fn,*a,**kw:fn(*a,**kw)
sys.modules['backend.db']=module
from backend import main, ai
from backend.routers.calm import return_state
from fastapi.testclient import TestClient

class CalmTests(unittest.TestCase):
    def setUp(self):
        db.rows={"journal_entries":[],"board_quests":[]};db.writes=[]
        folder = self.enterContext(TemporaryDirectory())
        self.enterContext(patch.dict(os.environ, {"LIAINNE_JOURNAL_DB": str(Path(folder) / "journal.sqlite3")}))
        self.client=TestClient(main.app)
    def test_startup_needs_no_ai_runtime_or_key(self):
        with patch.object(ai,'_build_client',side_effect=AssertionError('provider constructed')):
            with TestClient(main.app) as client:
                self.assertEqual(client.get('/ai/status').json()['enabled'],False)
                self.assertIsNone(main.embedding_model)
                self.assertNotIn('sentence_transformers',sys.modules)
    def test_note_mood_and_multiple_notes(self):
        for payload in ({'content':'A small moment'}, {'mood':4}, {'content':'Another moment'}):
            response=self.client.post('/entries',json=payload)
            self.assertEqual(response.status_code,200,response.text)
        entries = self.client.get('/entries').json()
        self.assertIsNone(entries[0]['mood'])
        self.assertEqual(len(entries), 3)
        self.assertEqual(db.writes, [])
    def test_empty_invalid_and_whitespace_not_saved(self):
        for payload in ({},{'content':'   '},{'mood':0},{'mood':6},{'title':'title only'}):
            self.assertEqual(self.client.post('/entries',json=payload).status_code,422)
        self.assertEqual(db.writes,[])
    def test_long_reflections_and_history(self):
        for kind in ['morning','night','free']:
            self.assertEqual(self.client.post('/entries',json={'content':'Synthetic reflection','entry_type':kind}).status_code,200)
        self.assertEqual(len(self.client.get('/calm/journal').json()),3)
    def test_absence_new_user_and_fourteen_days(self):
        self.assertTrue(return_state([], '2026-10-29')['new_user'])
        row={'created_at':'2026-10-15T02:00:00+00:00','tags':[]}
        self.assertTrue(return_state([row],'2026-10-29')['welcome_back'])
        self.assertFalse(return_state([row],'2026-10-21')['welcome_back'])
        self.assertTrue(return_state([row],'2026-10-22')['welcome_back'])
        main.journal_store.save(dict(row, entry_type='free', content='old', mood=None))
        db.rows['board_quests']=[{'id':1,'title':'old task','section':'daily','due_date':'2026-10-15','is_completed':False}]
        before=[r.copy() for r in db.rows['board_quests']]
        self.client.get('/calm/summary')
        self.client.get('/calm/tasks')
        self.client.post('/entries',json={'content':'Today is enough'})
        self.assertEqual(before,db.rows['board_quests'])
    def test_all_ai_routes_block_before_database_or_provider(self):
        with patch.object(ai,'_build_client',side_effect=AssertionError('provider constructed')):
            for path in main.AI_ROUTES | {'/skills/synthetic/mastery-check'}:
                for method in ('get','post'):
                    response=getattr(self.client,method)(path)
                    self.assertEqual(response.status_code,403,(path,response.text))
            for invoke in (lambda:ai.complete_chat([]),lambda:ai.groq_client.chat.completions.create(),lambda:main.generate_embedding('synthetic')):
                with self.assertRaises(main.HTTPException): invoke()
        self.assertEqual(db.writes,[])
    def test_background_embedding_does_nothing(self):
        main._backfill_entry_embedding(1,'synthetic')
        self.assertEqual(db.writes,[])
    def test_task_moves_preserve_history_and_undo(self):
        row={'id':1,'title':'older task','section':'daily','due_date':'2026-10-01','is_completed':False,'created_at':'2026-10-01T00:00:00Z'}
        db.rows['board_quests']=[row.copy()]
        for placement in ({'section':'daily','due_date':'2026-10-29'},{'section':'weekly','due_date':'2026-11-03'},{'section':'archived','due_date':'2026-10-01'}):
            result=self.client.put('/calm/tasks/1/placement',json=placement)
            self.assertEqual(result.status_code,200,result.text)
            previous=result.json()['previous']
            self.assertEqual(db.rows['board_quests'][0]['is_completed'],False)
            self.client.put('/calm/tasks/1/placement',json=previous)
            self.assertEqual(db.rows['board_quests'][0],row)
    def test_skip_and_automatic_generation_do_not_write(self):
        self.client.post('/entries/skip',json={})
        main._run_board_generation_if_due(force=True)
        self.assertEqual(main._gen_habit_recovery_quests(),[])
        self.assertEqual(db.writes,[])
    def test_save_failure_is_not_success_or_inference(self):
        with patch.object(main.journal_store,'save',side_effect=OSError('synthetic disk failure')):
            with TestClient(main.app,raise_server_exceptions=False) as client:
                self.assertEqual(client.post('/entries',json={'content':'retain this'}).status_code,500)
    def test_null_moods_in_trends(self):
        self.client.post('/entries', json={'content': 'No ratings recorded'})
        response = self.client.get('/entries/trends')
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()[0]['avg_mood'])

    def test_entry_lifecycle_stays_local(self):
        with patch.object(db, 'table', side_effect=AssertionError('remote access')):
            saved = self.client.post('/entries', json={'content': "A 10% win", 'tags': ['work']}).json()['entry']
            entry_id = saved['id']
            self.assertTrue(Path(os.environ['LIAINNE_JOURNAL_DB']).is_file())
            self.assertEqual(self.client.get('/entries', params={'keyword': '10%', 'tag': 'work'}).json(), [saved])
            later = TestClient(main.app)
            self.assertEqual(later.get(f'/entries/{entry_id}').json(), saved)
            self.assertEqual(later.get('/calm/journal').json(), [saved])
            self.assertEqual(later.get('/calm/summary').json()['recorded_days'], 1)
            edited = later.put(f'/entries/{entry_id}', json={'content': 'Edited', 'mood': 4}).json()['entry']
            self.assertEqual(edited['created_at'], saved['created_at'])
            self.assertEqual(later.delete(f'/entries/{entry_id}').status_code, 200)
            self.assertEqual(later.get(f'/entries/{entry_id}').status_code, 404)

    def test_journal_streak_freezes_cover_two_closed_days(self):
        streak = main.journal_store.journal_streak
        def record(timestamp, tags=()):
            main.journal_store.save({"content":"synthetic", "entry_type":"free",
                                     "created_at":timestamp, "tags":list(tags)})
        self.assertEqual(streak('2026-11-01'), {"recorded_days":0, "freezes_left":2})
        record('2026-10-31T16:01:00Z')  # November 1 in Manila
        record('2026-11-01T06:00:00Z')
        record('2026-11-02T01:00:00Z', ['__skipped__'])
        self.assertEqual(streak('2026-11-02'), {"recorded_days":1, "freezes_left":2})
        record('2026-11-03T00:00:00Z')
        self.assertEqual(streak('2026-11-05'), {"recorded_days":2, "freezes_left":0})
        self.assertEqual(streak('2026-11-06'), {"recorded_days":0, "freezes_left":2})
        record('2026-11-06T00:00:00Z')
        self.assertEqual(streak('2026-11-06'), {"recorded_days":1, "freezes_left":2})

    def test_provider_construction_itself_is_blocked(self):
        with self.assertRaises(main.HTTPException): ai._build_client()

    def test_reading_board_does_not_run_generators(self):
        main._invalidate_board_cache()
        with patch.object(main,'_get_board_quests',return_value=[]), patch.object(main,'_fetch_all_board_tasks_by_quest',return_value={}), patch.object(main,'_run_board_generation_if_due',side_effect=AssertionError('generated on read')):
            self.assertEqual(self.client.get('/board/quests').status_code,200)
        self.assertEqual(db.writes,[])

    def test_quick_checkin_accepts_mood_only_without_default_values(self):
        response=self.client.post('/quick-checkin',json={'entry':{'mood':4}})
        self.assertEqual(response.status_code,200,response.text)
        rows = main.journal_store.records()
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]['energy'])

    def test_participation_includes_more_than_one_database_page(self):
        with main.journal_store.connection() as conn:
            conn.executemany("INSERT INTO entries(created_at) VALUES (?)",
                             [('2026-10-29T01:00:00Z',)] * 1100)
        self.assertEqual(self.client.get('/calm/summary').json()['recorded_entries'],1100)

    def test_inactivity_does_not_reduce_live_mastery(self):
        db.rows['habit_profiles']=[{'name':'Reading','skill_tree':'Study','skill_node_id':'books'}]
        with patch.object(main,'_habit_quest_dates',return_value=['2026-10-01']), patch.object(main,'_build_habit_snapshot',return_value={'success_rate':75}) as snapshot:
            self.assertEqual(main._compute_node_habit_progress('Study','books'),75)
            self.assertEqual(snapshot.call_args.args[-1],'2026-10-01')
        self.assertEqual(db.writes,[])

if __name__=='__main__': unittest.main()
