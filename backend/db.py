"""Supabase client configuration and transient-connection retry helper."""
import logging
import os
import time

import httpx
from supabase import create_client
from supabase.lib.client_options import SyncClientOptions

logger = logging.getLogger("liainne.db")

_supabase_http_client = httpx.Client(
    http2=False,
    timeout=30,
    limits=httpx.Limits(max_keepalive_connections=5, keepalive_expiry=15),
)

supabase = create_client(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_KEY"],
    options=SyncClientOptions(httpx_client=_supabase_http_client),
)


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
