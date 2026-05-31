from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path
from typing import Any

_SESSION_ID = "c7d5cc"
_INGEST_URL = "http://127.0.0.1:7750/ingest/7035d313-172a-416d-a554-69960608899a"
_LOG_NAMES = ("debug-c7d5cc.log",)


def agent_debug_log(
    *,
    hypothesis_id: str,
    location: str,
    message: str,
    data: dict[str, Any] | None = None,
    run_id: str = "pre-fix",
) -> None:
    payload = {
        "sessionId": _SESSION_ID,
        "runId": run_id,
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data or {},
        "timestamp": int(time.time() * 1000),
    }
    line = json.dumps(payload, ensure_ascii=False) + "\n"
    for ingest_url in (_INGEST_URL, "http://host.docker.internal:7750/ingest/7035d313-172a-416d-a554-69960608899a"):
        try:
            req = urllib.request.Request(
                ingest_url,
                data=line.encode("utf-8"),
                headers={"Content-Type": "application/json", "X-Debug-Session-Id": _SESSION_ID},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=1)
            break
        except Exception:
            continue
    candidates = [Path.cwd() / name for name in _LOG_NAMES]
    try:
        candidates.append(Path(__file__).resolve().parents[3] / _LOG_NAMES[0])
    except IndexError:
        pass
    for path in candidates:
        try:
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(line)
            break
        except Exception:
            continue
