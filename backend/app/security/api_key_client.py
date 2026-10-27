"""The client side of the API key: the header a harness sends, not the rule that checks it.

Apart from api_key.py on purpose. That module imports FastAPI and the auth layer (JWT, the
ORM models), and an eval harness that only builds a header should load neither: importing
scripts.evaluate_rag took 0.81 s through api_key.py against 0.22 s without (27/10/2026).
Nothing here imports beyond the standard library at module level.
"""
from __future__ import annotations

import os


def api_key_headers() -> dict[str, str]:
    """The X-API-Key header the server will actually enforce, if any.

    Reading only os.environ was a silent outage. On 27/08 the operator put
    LOCAL_AI_API_KEY in .env; the server (pydantic-settings, which loads .env)
    began enforcing it, while this harness kept looking at a variable that no
    Scheduled Task exports. Every nightly run from 27/08 to 04/09 died 401 on
    the first upload — a red gate that said nothing at all about retrieval.

    Falling back to Settings reads the same file the server reads, so the two
    cannot drift apart again. An explicit env var still wins, which is what CI
    and one-off runs against another host rely on.
    """
    key = os.environ.get("LOCAL_AI_API_KEY", "").strip()
    if not key:
        try:
            from app.config.settings import get_settings

            key = (get_settings().local_ai_api_key or "").strip()
        except Exception:
            # A run pointed at a remote base URL need not have a local .env or
            # a reachable database. Send no header rather than refuse to start.
            key = ""
    return {"X-API-Key": key} if key else {}
