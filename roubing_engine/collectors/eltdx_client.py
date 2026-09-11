"""Thin eltdx wrapper: connection, code conversion, small retry."""
from __future__ import annotations

import time
from contextlib import contextmanager

from eltdx import TdxClient

from roubing_engine.config import DEFAULT_TIMEOUT


def to_eltdx_code(code: str) -> str:
    """Convert a thscode-like code to eltdx full_code.

    '000001.SZ' -> 'sz000001'; '600000.SH' -> 'sh600000'; 'sz000001' stays.
    """
    code = code.strip()
    if code[:2].lower() in ("sz", "sh", "bj"):
        return code.lower()
    if "." in code:
        num, ex = code.split(".")
        return f"{ex.lower()}{num}"
    # bare number: infer by prefix (best-effort)
    if code.startswith(("60", "68", "9")):
        return f"sh{code}"
    if code.startswith(("4", "8", "92")):
        return f"bj{code}"
    return f"sz{code}"


def to_thscode(full_code: str) -> str:
    """'sz000001' -> '000001.SZ'."""
    ex, num = full_code[:2], full_code[2:]
    return f"{num}.{ex.upper()}"


@contextmanager
def client(timeout: int = DEFAULT_TIMEOUT):
    c = TdxClient(timeout=timeout)
    c.__enter__()
    try:
        yield c
    finally:
        c.__exit__(None, None, None)


def with_retry(fn, *args, retries: int = 3, backoff: float = 0.8, **kwargs):
    """Retry a callable a few times; raise the last error on exhaustion."""
    last = None
    for attempt in range(retries):
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001 - collector must surface any tdx error
            last = e
            time.sleep(backoff * (attempt + 1))
    raise last
