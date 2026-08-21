"""HTTP transport, with an optional browser TLS fingerprint.

Ten marketplaces refuse this client in ~110ms from a residential connection in
Portugal — including olx.pt, refusing a Portuguese address. That rules out both
geo-fencing and IP reputation, and it is far too fast for anything to have read
the request. What is left is the handshake itself: Python's TLS ClientHello
(JA3/JA4) and its HTTP/2 SETTINGS frame do not look like any browser, and
Cloudflare, Akamai and DataDome all reject on that signature at the edge.

`curl_cffi` wraps curl-impersonate, which reproduces Chrome's exact handshake.
It is an optional dependency: when it is missing the engines fall back to plain
httpx and say so, rather than failing to import.

Everything here normalises back to httpx types — responses and exceptions — so
the engines and their error handling stay written against one model.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)

try:  # pragma: no cover - import availability is environment-specific
    from curl_cffi.requests import AsyncSession as _CurlAsyncSession

    _IMPORT_ERROR: str | None = None
except Exception as exc:  # ImportError, or a broken native build
    _CurlAsyncSession = None
    _IMPORT_ERROR = f"{type(exc).__name__}: {exc}"

# curl-impersonate profile. Chrome is the safest default: it is the fingerprint
# these sites see most, so it is the one they cannot afford to reject.
DEFAULT_PROFILE = "chrome124"


def available() -> bool:
    return _CurlAsyncSession is not None


def unavailable_reason() -> str:
    return _IMPORT_ERROR or "not installed"


# curl has already applied these by the time we see the body; passing them on
# would make httpx try to decode an already-decoded payload a second time.
_CONSUMED_HEADERS = {"content-encoding", "content-length", "transfer-encoding"}


def _to_httpx(response: Any, method: str, url: str) -> httpx.Response:
    """Re-wrap a curl_cffi response as an httpx one.

    Keeps a single response and exception model across both transports, so
    engines never branch on which transport served them.

    The header filtering is load-bearing rather than tidiness: curl transparently
    decompresses, so ``response.content`` is plain bytes while the headers still
    advertise ``Content-Encoding: gzip``. Forwarding that pair makes httpx
    inflate the body again and raise DecodingError on every gzipped site — which
    is exactly how this first shipped.
    """
    headers = {
        key: value
        for key, value in dict(response.headers).items()
        if key.lower() not in _CONSUMED_HEADERS
    }
    return httpx.Response(
        status_code=response.status_code,
        headers=headers,
        content=response.content,
        request=httpx.Request(method, url),
    )


class BrowserTransport:
    """A curl_cffi session presenting a real Chrome TLS/HTTP2 fingerprint.

    Holds cookies across calls, so multi-step flows (fetch a page to obtain a
    session cookie, then call the API with it) behave as they do on httpx.
    """

    def __init__(self, profile: str = DEFAULT_PROFILE) -> None:
        self.profile = profile
        self._session: Any | None = None

    def _ensure(self) -> Any:
        if self._session is None:
            self._session = _CurlAsyncSession(impersonate=self.profile)
        return self._session

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        content: bytes | None = None,
        data: dict[str, str] | None = None,
        timeout: float = 20.0,
    ) -> httpx.Response:
        session = self._ensure()
        try:
            response = await session.request(
                method,
                url,
                params=params,
                # curl-impersonate supplies its own browser-shaped header set and
                # ordering; ours would undo the disguise if it overrode them.
                headers={k: v for k, v in (headers or {}).items()
                         if k.lower() not in ("user-agent", "accept-encoding")},
                data=content if content is not None else data,
                timeout=timeout,
                allow_redirects=True,
            )
        except Exception as exc:  # normalise to the model engines already catch
            raise httpx.ConnectError(f"{type(exc).__name__}: {exc}") from exc
        return _to_httpx(response, method, url)

    async def aclose(self) -> None:
        if self._session is not None:
            try:
                await self._session.close()
            except Exception:  # a failed close must not fail a search
                log.debug("browser transport close failed", exc_info=True)
            self._session = None
