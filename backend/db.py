"""Supabase client configuration and transient-connection retry helper."""
from functools import lru_cache
from fastapi import HTTPException
import logging
import os
import time

import httpx

logger = logging.getLogger("liainne.db")

@lru_cache(maxsize=1)
def _remote_client():
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise HTTPException(503, "Configure Supabase to use this optional tool.")
    from supabase import create_client
    from supabase.lib.client_options import SyncClientOptions
    client = httpx.Client(http2=False, timeout=30,
                          limits=httpx.Limits(max_keepalive_connections=5, keepalive_expiry=15))
    return create_client(url, key, options=SyncClientOptions(httpx_client=client))


class RemoteTables:
    def table(self, name):
        mode = os.getenv("LIAINNE_DATA_BACKEND", "sqlite")
        if mode == "supabase":
            return _remote_client().table(name)
        if mode != "sqlite":
            raise ValueError("LIAINNE_DATA_BACKEND must be sqlite or supabase")
        from backend.local_store import Query
        return Query(name)


supabase = RemoteTables()


def db_retry(fn, *args, retries: int = 2, delay: float = 0.3, **kwargs):
    """Retry a database operation after a transient pooled-connection failure."""
    last_exc = None
    for attempt in range(retries + 1):
        try:
            return fn(*args, **kwargs)
        except (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadError, httpx.ConnectTimeout) as exc:
            last_exc = exc
            logger.warning(
                "db_retry: attempt %d/%d failed for %s: %s",
                attempt + 1,
                retries + 1,
                getattr(fn, "__name__", fn),
                exc,
            )
            if attempt < retries:
                time.sleep(delay * (attempt + 1))
    raise last_exc
