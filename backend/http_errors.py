"""Map LLM client failures to HTTP responses the UI can show clearly."""
from __future__ import annotations

from fastapi import HTTPException

_NETWORK_MSG = (
    "Cannot reach the AI provider (DNS or network). Check your internet connection, "
    "disable VPN/proxy if misconfigured, and retry."
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


def http_exception_from_llm_error(exc: Exception) -> HTTPException:
    if is_network_error(exc):
        return HTTPException(status_code=503, detail=_NETWORK_MSG)
    return HTTPException(status_code=400, detail=f"{type(exc).__name__}: {exc}")
