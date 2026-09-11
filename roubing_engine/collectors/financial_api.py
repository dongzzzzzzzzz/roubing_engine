"""Financial-API (fuyao) REST client: index & stock daily, limit reasons.

Key is read from env HITHINK_FINANCE_API_KEY (loaded from .env if present).
Never logged or committed. Success requires HTTP 200 AND body code == 0.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.parse
from pathlib import Path

BASE = "https://fuyao.aicubes.cn"
_ENV = Path(__file__).resolve().parent.parent.parent / ".env"


def _load_key() -> str:
    key = os.environ.get("HITHINK_FINANCE_API_KEY")
    if not key and _ENV.exists():
        for line in _ENV.read_text().splitlines():
            if line.startswith("HITHINK_FINANCE_API_KEY="):
                key = line.split("=", 1)[1].strip()
                break
    if not key:
        raise RuntimeError("HITHINK_FINANCE_API_KEY not set (env or .env)")
    return key


def get(path: str, params: dict, retries: int = 3) -> dict:
    """GET via curl (uses macOS system trust store; env Python misses corp CA).

    Requires HTTP body code == 0. The API key is passed as a header arg to curl
    (not interpolated into the URL) and is never logged by this module.
    """
    key = _load_key()
    url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
    last = None
    for attempt in range(retries):
        try:
            proc = subprocess.run(
                ["curl", "-s", "-m", "25", url, "-H", f"X-api-key: {key}"],
                capture_output=True, text=True, check=True,
            )
            body = json.loads(proc.stdout)
            if body.get("code") != 0:
                raise RuntimeError(f"biz error code={body.get('code')} msg={body.get('message')}")
            return body.get("data") or {}
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(0.8 * (attempt + 1))
    raise last


def _ms(date_iso: str) -> int:
    import datetime as dt
    from zoneinfo import ZoneInfo
    d = dt.date.fromisoformat(date_iso)
    local_midnight = dt.datetime(d.year, d.month, d.day, tzinfo=ZoneInfo("Asia/Shanghai"))
    return int(local_midnight.timestamp() * 1000)


def index_daily(thscode: str, start: str, end: str) -> list[dict]:
    """Index daily bars in [start, end] (YYYY-MM-DD). Returns list of dict rows."""
    data = get("/api/a-share-index/prices/historical", {
        "thscode": thscode, "interval": "1d",
        "start": _ms(start), "end": _ms(end) + 86_400_000,
    })
    return data.get("item", []) or []


def index_snapshot(thscodes: list[str]) -> list[dict]:
    data = get("/api/a-share-index/prices/snapshot", {"thscodes": ",".join(thscodes)})
    return data.get("item", []) or []
