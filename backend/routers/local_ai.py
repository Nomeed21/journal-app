"""Explicit preview/send API, independent of the permanently disabled legacy coach."""
import asyncio
from contextlib import suppress
import json
import os
import logging
import time

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from backend import ollama
from backend.journal_store import connection

router = APIRouter(prefix="/api/ai")
logger = logging.getLogger("liainne.local_ai")


class Settings(BaseModel):
    enabled: bool
    model: str
    reasoning: bool = False


class Ask(BaseModel):
    passage: str = Field(max_length=500_000)
    question: str = Field(max_length=20_000)
    model: str | None = None


def settings():
    with connection() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS local_ai_preferences (id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER, model TEXT, reasoning INTEGER)")
        row = conn.execute("SELECT enabled,model,reasoning FROM local_ai_preferences WHERE id=1").fetchone()
    if row:
        return Settings(**dict(row))
    default = os.getenv("OLLAMA_MODEL","qwen3:4b")
    return Settings(enabled=os.getenv("LOCAL_AI_ENABLED","false").lower()=="true",
                    model="qwen3:4b" if "coder" in default.lower() else default)


@router.put("/settings")
def update_settings(change: Settings):
    ollama.model_name(change.model)
    settings()
    with connection() as conn:
        conn.execute("INSERT OR REPLACE INTO local_ai_preferences VALUES (1,?,?,?)",
                     (change.enabled,change.model,change.reasoning))
    return change


@router.get("/status")
async def status(probe: bool = False):
    current = settings()
    data = {**current.model_dump(),"reachable":None,"models":[],"pull_command":None,
            "state":"Off","message":"AI processing is off."}
    if not current.enabled and not probe:
        return data
    try:
        async with ollama.client() as http:
            names = await ollama.models(http)
        data.update(reachable=True, models=names)
        if current.model not in names:
            data.update(state="Model not installed",message=ollama.missing(current.model),
                        pull_command="ollama pull "+current.model)
        else:
            data.update(state="Ready (local)" if current.enabled else "Off",message="Connected")
    except (HTTPException,httpx.HTTPError,ValueError,KeyError) as exc:
        data.update(reachable=False,state="Ollama not running",message=ollama.failure(exc).detail)
    return data


def prepare(body):
    current = settings()
    if not current.enabled:
        raise HTTPException(403, "Local AI is off. Enable it in Settings to use this feature.")
    return current, ollama.preview(body.passage,body.question,body.model or current.model)


@router.post("/preview")
def preview(body: Ask):
    current, plan = prepare(body)
    return {**plan, "reasoning":current.reasoning}


@router.post("/ask")
async def ask(body: Ask, request: Request):
    current, plan = prepare(body)
    started = time.monotonic()
    stream = ollama.generate(plan,current.reasoning)
    # Surface connection/model errors with an HTTP status before sending headers.
    # Stop also closes the upstream request while Ollama is loading the model,
    # before the first response chunk or StreamingResponse headers exist.
    pending = asyncio.create_task(anext(stream))
    try:
        while not pending.done():
            await asyncio.wait({pending}, timeout=0.15)
            if await request.is_disconnected():
                raise HTTPException(499, "Local AI request stopped.")
        first = pending.result()
    except BaseException:
        pending.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await pending
        await stream.aclose()
        raise
    async def events():
        try:
            yield json.dumps(first)+"\n"
            async for event in stream:
                yield json.dumps(event)+"\n"
        except HTTPException as exc:
            yield json.dumps({"type":"error","text":exc.detail})+"\n"
        finally:
            await stream.aclose()
            logger.info("Local AI stream closed after %.2fs", time.monotonic()-started)
    return StreamingResponse(events(),media_type="application/x-ndjson",
                             headers={"Cache-Control":"no-store","X-Accel-Buffering":"no"},
                             background=BackgroundTask(stream.aclose))

