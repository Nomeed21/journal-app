"""Shared chat-completion client (Groq cloud or local Ollama).

Call sites should use `complete_chat(...)` rather than talking to Groq/Ollama
directly. That keeps model ids, think-tag stripping, empty-content handling,
and provider URLs in one place.
"""
from __future__ import annotations

import logging
import os
import re

from fastapi import HTTPException

from backend.bootstrap_env import PROJECT_ROOT  # noqa: F401  (loads .env on import)

logger = logging.getLogger("liainne.ai")

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama").strip().lower()


def _default_model() -> str:
    explicit = (os.getenv("LLM_MODEL") or "").strip()
    if explicit:
        return explicit
    if LLM_PROVIDER == "ollama":
        return "qwen3:8b"
    # Groq retired llama-3.3-70b-versatile on 2026-08-16.
    return "openai/gpt-oss-20b"


LLM_MODEL = _default_model()


def _timeout_seconds() -> float:
    default = "180" if LLM_PROVIDER == "ollama" else "30"
    return float(os.getenv("LLM_TIMEOUT_SECONDS", default))


def _build_client():
    require_ai()
    from groq import Groq
    timeout = _timeout_seconds()
    if LLM_PROVIDER == "ollama":
        base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1").rstrip("/")
        api_key = os.getenv("OLLAMA_API_KEY") or "ollama"
        logger.info("AI provider=ollama model=%s base_url=%s timeout=%ss", LLM_MODEL, base_url, timeout)
        return Groq(api_key=api_key, base_url=base_url, timeout=timeout)

    api_key = (os.environ.get("GROQ_API_KEY") or "").strip()
    if not api_key or api_key == "your-groq-api-key-here":
        raise RuntimeError(
            "GROQ_API_KEY is missing or still the placeholder. "
            "Put a real key in .env, or set LLM_PROVIDER=ollama."
        )
    logger.info("AI provider=groq model=%s timeout=%ss", LLM_MODEL, timeout)
    return Groq(api_key=api_key, timeout=timeout)


# AI is deliberately unavailable in this release. Environment/provider settings
# do not constitute consent to send journal history. A future opt-in must scope
# and preview each submission before this policy can be changed.
AI_ENABLED = False

def require_ai():
    raise HTTPException(403, "AI processing is off. Journal entries are stored locally.")

class DisabledClient:
    @property
    def chat(self):
        return self

    @property
    def completions(self):
        return self

    def create(self, *args, **kwargs):
        require_ai()

groq_client = DisabledClient()


def _extract_text(message) -> str:
    text = (getattr(message, "content", None) or "").strip()
    if text:
        return text
    for attr in ("reasoning", "reasoning_content"):
        extra = getattr(message, attr, None)
        if extra:
            return str(extra).strip()
    return ""


def _strip_think(text: str) -> str:
    return _THINK_RE.sub("", text or "").strip()


def complete_chat(
    messages: list[dict],
    *,
    temperature: float = 0.7,
    max_tokens: int = 400,
) -> str:
    """Run one chat completion and return cleaned assistant text."""
    create_kwargs = dict(
        model=LLM_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    # Qwen3 spends tokens on a hidden chain-of-thought unless thinking is off.
    if LLM_PROVIDER == "ollama" and "qwen3" in LLM_MODEL.lower():
        create_kwargs["extra_body"] = {"think": False}

    try:
        response = groq_client.chat.completions.create(**create_kwargs)
    except TypeError:
        create_kwargs.pop("extra_body", None)
        response = groq_client.chat.completions.create(**create_kwargs)

    if not response.choices:
        raise RuntimeError(f"Empty choices from {LLM_PROVIDER}/{LLM_MODEL}")
    text = _strip_think(_extract_text(response.choices[0].message))
    if not text:
        raise RuntimeError(f"Empty content from {LLM_PROVIDER}/{LLM_MODEL}")
    return text
