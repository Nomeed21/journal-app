"""No Ollama process, API keys, remote database or journal content is used here."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from backend import ollama
from backend.main import app


REAL_CLIENT = ollama.client


class LocalAITests(unittest.TestCase):
    def setUp(self):
        folder = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.dict(os.environ, {"LIAINNE_JOURNAL_DB":str(Path(folder)/"test.sqlite3"),
            "LOCAL_AI_ENABLED":"false","OLLAMA_MODEL":"qwen3:4b","OLLAMA_NUM_CTX":"4096"}))
        self.calls = []
        self.scenario = "ok"
        self.enterContext(patch.object(ollama, "client", lambda: httpx.AsyncClient(
            base_url="http://localhost:11434",transport=httpx.MockTransport(self.respond))))
        self.client = self.enterContext(TestClient(app))
        self.body = {"passage":"Synthetic passage.", "question":"What mattered?"}

    def respond(self, request):
        path=request.url.path
        data=json.loads(request.content) if request.content else None
        self.calls.append((path,data))
        if self.scenario=="offline": raise httpx.ConnectError("synthetic offline")
        if self.scenario=="timeout": raise httpx.ReadTimeout("synthetic timeout")
        if path=="/api/tags":
            names=[] if self.scenario=="missing" else ["qwen3:4b","qwen2.5-coder:1.5b"]
            return httpx.Response(200,json={"models":[{"name":n} for n in names]})
        if path=="/api/show":
            return httpx.Response(200,json={"remote_host":"example.invalid"} if self.scenario=="remote" else {})
        self.assertEqual(path,"/api/chat")
        if self.scenario=="old" and "think" in data:
            return httpx.Response(400,json={"error":"unknown field think"})
        parts=["An answer. <th","ink>hidden"," notes</thi","nk> Thank you."]
        frames=[{"message":{"content":p,"thinking":"internal" if i==0 else ""},"done":False}
                for i,p in enumerate(parts)]
        frames.append({"done":True,"message":{}})
        return httpx.Response(200,content="\n".join(json.dumps(x) for x in frames))

    def enable(self, reasoning=False):
        self.assertEqual(self.client.put('/api/ai/settings',json={
            'enabled':True,'model':'qwen3:4b','reasoning':reasoning}).status_code,200)

    def ask(self):
        res=self.client.post('/api/ai/ask',json=self.body)
        self.assertEqual(res.status_code,200,res.text)
        return [json.loads(line) for line in res.text.splitlines()]

    def test_off_default_and_direct_calls(self):
        self.assertFalse(self.client.get('/api/ai/status').json()['enabled'])
        for path in ('preview','ask'):
            self.assertEqual(self.client.post('/api/ai/'+path,json=self.body).status_code,403)
        self.assertFalse(self.calls)

    def test_status_only_probes_metadata(self):
        self.enable()
        result=self.client.get('/api/ai/status').json()
        self.assertTrue(result['reachable'])
        self.assertEqual(result['state'],'Ready (local)')
        self.assertIn('qwen3:4b',result['models'])
        self.assertEqual(self.calls,[('/api/tags',None)])

    def test_preview_and_sent_messages_are_identical(self):
        self.enable()
        self.body['passage']='界'*5000
        plan=self.client.post('/api/ai/preview',json=self.body).json()
        self.assertGreater(plan['cut_characters'],0)
        self.assertEqual(plan['messages'][1]['content'].count('界'),5000-plan['cut_characters'])
        self.assertFalse(self.calls)
        frames=self.ask()
        payload=self.calls[-1][1]
        self.assertEqual(payload['messages'],plan['messages'])
        self.assertFalse(payload['think'])
        self.assertEqual(payload['options']['num_ctx'],4096)
        self.assertEqual(payload['options']['temperature'],0.6)
        self.assertEqual(payload['keep_alive'],'5m')
        self.assertEqual(''.join(e['text'] for e in frames if e['type']=='answer'),'An answer.  Thank you.')
        self.assertNotIn('internal',str(frames))
        self.assertNotIn('hidden',str(frames))

    def test_reasoning_is_separate_and_opt_in(self):
        self.enable(True)
        frames=self.ask()
        self.assertTrue(self.calls[-1][1]['think'])
        self.assertIn('hidden notes',''.join(e['text'] for e in frames if e['type']=='thinking'))
        self.assertNotIn('hidden', ''.join(e['text'] for e in frames if e['type']=='answer'))

    def test_old_server_retries_once_without_think(self):
        self.enable()
        self.scenario='old'
        frames=self.ask()
        calls=[data for path,data in self.calls if path=='/api/chat']
        self.assertEqual(len(calls),2)
        self.assertNotIn('think',calls[1])
        self.assertEqual(frames[0]['type'],'note')
        self.assertNotIn('hidden',str(frames))

    def test_model_missing_down_timeout_and_cloud_alias(self):
        self.enable()
        for case,code in [('missing',409),('offline',503),('timeout',504),('remote',422)]:
            with self.subTest(case=case):
                self.scenario=case
                status=self.client.get('/api/ai/status').json()
                if case=='missing':
                    self.assertEqual(status['pull_command'],'ollama pull qwen3:4b')
                if case=='offline':
                    self.assertFalse(status['reachable'])
                res=self.client.post('/api/ai/ask',json=self.body)
                self.assertEqual(res.status_code,code)
                self.assertFalse(any(path=='/api/chat' for path,_ in self.calls))

    def test_entry_workflows_do_not_touch_ollama_even_when_enabled(self):
        self.enable()
        saved=self.client.post('/entries',json={'content':'Synthetic entry'}).json()['entry']
        self.client.get('/calm/journal')
        self.client.put('/entries/'+str(saved['id']),json={'content':'Edited synthetic entry'})
        self.assertFalse(self.calls)



    def test_disabled_connection_test_only_lists_models(self):
        result=self.client.get('/api/ai/status?probe=true').json()
        self.assertFalse(result['enabled'])
        self.assertTrue(result['reachable'])
        self.assertEqual(self.calls,[('/api/tags',None)])

    def test_nonloopback_or_redirect_base_rejected_before_network(self):
        # Inspect the actual constructor, not the mock transport.
        from fastapi import HTTPException
        for url in ('https://ollama.com','http://localhost@external.invalid','http://127.0.0.1/v1'):
            with patch.dict(os.environ,{'OLLAMA_BASE_URL':url}):
                with self.assertRaises(HTTPException):
                    REAL_CLIENT()
