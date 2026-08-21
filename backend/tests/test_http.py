"""The browser-fingerprint transport.

Ten marketplaces refuse plain Python clients at the TLS handshake — verified
from a residential Portuguese connection, including olx.pt refusing a
Portuguese address, which rules out geo and IP reputation. These tests cover
the transport that answers that, and — just as important — that a missing
optional dependency degrades instead of exploding.
"""

import httpx
import pytest
import respx

from ufeu import http as ufeu_http
from ufeu.adapters import build_engine
from ufeu.catalog import load_catalog
from ufeu.models import ResultStatus, SearchQuery


@pytest.fixture(scope="module")
def catalog():
    return load_catalog()


def test_impersonate_reads_the_catalog(catalog):
    client = httpx.AsyncClient()
    olx = build_engine(catalog.by_id["olx_pt"], client, {})
    bazos = build_engine(catalog.by_id["bazos_cz"], client, {})

    assert olx.impersonate == "chrome124"
    assert bazos.impersonate is None, "sites that work plainly must not pay the impersonation cost"


def test_impersonate_true_falls_back_to_the_default_profile(catalog):
    market = catalog.by_id["bazos_cz"].model_copy(deep=True)
    market.engine_config["impersonate"] = True
    engine = build_engine(market, httpx.AsyncClient(), {})
    assert engine.impersonate == ufeu_http.DEFAULT_PROFILE


@respx.mock
async def test_missing_curl_cffi_degrades_to_httpx_with_a_warning(catalog, caplog, monkeypatch):
    """A missing optional dependency must mean "probably blocked", never "cannot run"."""
    monkeypatch.setattr(ufeu_http, "_CurlAsyncSession", None)
    route = respx.get(url__startswith="https://www.olx.pt/api/v1/offers/").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    async with httpx.AsyncClient() as client:
        engine = build_engine(catalog.by_id["olx_pt"], client, {})
        with caplog.at_level("WARNING"):
            result = await engine.run(SearchQuery(q="iphone", limit=5))

    assert route.called, "must still attempt the request over plain httpx"
    assert result.status is ResultStatus.EMPTY
    assert "curl_cffi is unavailable" in caplog.text
    assert "pip install curl_cffi" in caplog.text


@respx.mock
async def test_the_warning_is_logged_once_not_per_request(catalog, caplog, monkeypatch):
    monkeypatch.setattr(ufeu_http, "_CurlAsyncSession", None)
    respx.get(url__startswith="https://www.olx.pt/").mock(return_value=httpx.Response(200, json={"data": []}))
    async with httpx.AsyncClient() as client:
        engine = build_engine(catalog.by_id["olx_pt"], client, {})
        with caplog.at_level("WARNING"):
            await engine.fetch("https://www.olx.pt/a")
            await engine.fetch("https://www.olx.pt/b")
    assert caplog.text.count("curl_cffi is unavailable") == 1


class _FakeCurlResponse:
    def __init__(self, status_code, content, headers=None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {"content-type": "application/json"}


def test_curl_responses_become_real_httpx_responses():
    """One response and exception model across both transports, so engines and
    their error handling never branch on which one served them."""
    converted = ufeu_http._to_httpx(
        _FakeCurlResponse(200, b'{"data": [1, 2]}'), "GET", "https://example.com/x"
    )
    assert isinstance(converted, httpx.Response)
    assert converted.json() == {"data": [1, 2]}
    assert converted.status_code == 200

    failure = ufeu_http._to_httpx(_FakeCurlResponse(403, b"nope"), "GET", "https://example.com/x")
    with pytest.raises(httpx.HTTPStatusError):
        failure.raise_for_status()


async def test_transport_errors_are_normalised_to_httpx(monkeypatch):
    """base.run() catches httpx.RequestError; a curl-native exception escaping
    it would surface as an unhandled crash instead of a tidy result row."""

    class _ExplodingSession:
        async def request(self, *args, **kwargs):
            raise RuntimeError("curl: (35) TLS connect error")

        async def close(self):
            pass

    transport = ufeu_http.BrowserTransport()
    transport._session = _ExplodingSession()
    with pytest.raises(httpx.ConnectError) as excinfo:
        await transport.request("GET", "https://example.com")
    assert "TLS connect error" in str(excinfo.value)
    await transport.aclose()


def test_availability_reports_a_reason_when_absent():
    # Whatever the environment, the pair must be self-consistent.
    if ufeu_http.available():
        assert ufeu_http.unavailable_reason() == "not installed"
    else:
        assert ufeu_http.unavailable_reason()


@pytest.mark.parametrize("encoding", ["gzip", "br", "zstd", "deflate"])
def test_already_decoded_bodies_are_not_decoded_twice(encoding):
    """curl decompresses transparently, so the body is plain while the headers
    still claim an encoding. Forwarding both made httpx inflate it again and
    raise DecodingError on every gzipped site — eight of them, in practice."""
    response = ufeu_http._to_httpx(
        _FakeCurlResponse(
            200,
            b'{"data": [{"id": 1}]}',
            headers={"content-type": "application/json", "content-encoding": encoding,
                     "content-length": "999"},
        ),
        "GET",
        "https://www.olx.pt/api/v1/offers/",
    )
    # The bug surfaced on read, not on construction.
    assert response.json() == {"data": [{"id": 1}]}
    assert "content-encoding" not in response.headers
    # httpx recomputes content-length from the real body; the stale value curl
    # reported for the *compressed* payload must not survive.
    assert response.headers["content-length"] == "21"
    assert response.headers["content-type"] == "application/json"


def test_meaningful_headers_survive_the_conversion():
    response = ufeu_http._to_httpx(
        _FakeCurlResponse(200, b"ok", headers={"content-type": "text/html", "set-cookie": "a=1"}),
        "GET", "https://example.com",
    )
    assert response.headers["set-cookie"] == "a=1"
