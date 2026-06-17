"""Map LLM client failures to HTTP responses the UI can show clearly."""
from __future__ import annotations

from fastapi import HTTPException

_NETWORK_MSG = (
    "Cannot reach the AI provider (DNS or network). Check your internet connection, "
    "disable VPN/proxy if misconfigured, and retry."
)

_EXPENSE_CAP_MSG = (
    "AI usage expense cap reached. Image and design generation are paused until your API "
    "quota resets or billing is updated. Try again later, or ask your admin to increase the limit."
)

_EXPENSE_CAP_MARKERS = (
    "expense cap",
    "spending cap",
    "quota exceeded",
    "exceeded your current quota",
    "resource_exhausted",
    "resource exhausted",
    "rate limit",
    "rate_limit",
    "too many requests",
    "billing",
    "paid plan",
    "insufficient quota",
    "quota limit",
    "usage limit",
    "budget exceeded",
)


def is_network_error(exc: BaseException) -> bool:
    """True for DNS failures, refused connections, and similar transport errors."""
    try:
        import httpx
    except ImportError:
        httpx = None  # type: ignore[assignment]

    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if httpx is not None and isinstance(cur, (httpx.ConnectError, httpx.NetworkError, httpx.TimeoutException)):
            return True
        if isinstance(cur, (ConnectionError, TimeoutError, OSError)):
            winerr = getattr(cur, "winerror", None)
            if winerr == 11001 or getattr(cur, "errno", None) in (11001, -2, -3, 11002):
                return True
            if isinstance(cur, ConnectionError):
                return True
        low = str(cur).lower()
        if "getaddrinfo failed" in low or "name or service not known" in low or "temporary failure in name resolution" in low:
            return True
        cur = cur.__cause__ or cur.__context__
    return False


def is_expense_cap_error(exc: BaseException) -> bool:
    """True for API quota, billing, and rate-limit failures."""
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        for attr in ("code", "status_code", "status"):
            code = getattr(cur, attr, None)
            try:
                if int(code) == 429:
                    return True
            except (TypeError, ValueError):
                pass
        low = str(cur).lower()
        if any(marker in low for marker in _EXPENSE_CAP_MARKERS):
            return True
        cur = cur.__cause__ or cur.__context__
    return False


def http_exception_from_llm_error(exc: Exception) -> HTTPException:
    if is_network_error(exc):
        return HTTPException(status_code=503, detail=_NETWORK_MSG)
    if is_expense_cap_error(exc):
        return HTTPException(status_code=429, detail=_EXPENSE_CAP_MSG)
    return HTTPException(status_code=400, detail=f"{type(exc).__name__}: {exc}")
