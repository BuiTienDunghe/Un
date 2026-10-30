"""Ticket 35: the web tools, with no network: parsing, the address guard, and what may be opened."""
from __future__ import annotations

import json
import socket
from types import SimpleNamespace

import httpx
import pytest

from app.services import web_tools
from app.services.agent_service import AgentService, core_tools

RESULTS_HTML = """
<div class="result"><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fvnexpress.net%2Fbai-1&amp;rut=x">Giá <b>vàng</b> hôm nay</a>
<a class="result__snippet" href="x">Giá vàng tăng &amp; giảm</a></div>
<div class="result"><a class="result__a" href="https://duckduckgo.com/y.js?ad=1">Quảng cáo</a></div>
<div class="result"><a class="result__a" href="https://example.org/2">Bài hai</a></div>
"""


def agent() -> AgentService:
    registry = core_tools()
    web_tools.register(registry)
    return AgentService(SimpleNamespace(models={"general": {"name": "m"}}), SimpleNamespace(), SimpleNamespace(), registry=registry)


def resolving_to(monkeypatch, address: str) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", (address, 443))])


def test_results_keep_the_real_url_and_drop_ads() -> None:
    results = web_tools.parse_results(RESULTS_HTML, 5)
    assert [item["url"] for item in results] == ["https://vnexpress.net/bai-1", "https://example.org/2"]
    assert results[0]["title"] == "Giá vàng hôm nay" and results[0]["snippet"] == "Giá vàng tăng & giảm"


def test_page_text_leaves_out_scripts_and_menus() -> None:
    title, text = web_tools.page_text("<html><head><title> Tin </title><script>alert(1)</script></head><body><nav>Menu</nav><p>Nội dung</p><p>Đoạn hai</p></body></html>")
    assert title == "Tin" and text == "Nội dung\nĐoạn hai"


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254", "::1", "172.17.0.1", "100.64.0.1"])
def test_private_addresses_are_not_public(monkeypatch, address) -> None:
    resolving_to(monkeypatch, address)
    assert web_tools.public_address("https://looks-fine.example/") is False


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.org/x", "https://user:pw@example.org/", "https://example.org:8000/", "gopher://x"])
def test_other_schemes_ports_and_credentials_are_refused(monkeypatch, url) -> None:
    resolving_to(monkeypatch, "93.184.216.34")
    assert web_tools.public_address(url) is False


def test_a_public_host_passes(monkeypatch) -> None:
    resolving_to(monkeypatch, "93.184.216.34")
    assert web_tools.public_address("https://example.org/a") is True


def test_a_redirect_to_this_machine_is_stopped(monkeypatch) -> None:
    monkeypatch.setattr(web_tools, "public_address", lambda url: "localhost" not in url)
    transport = httpx.MockTransport(lambda request: httpx.Response(302, headers={"location": "http://localhost:8000/documents"}))
    original = httpx.Client
    monkeypatch.setattr(web_tools.httpx, "Client", lambda **kwargs: original(transport=transport, **kwargs))
    with pytest.raises(ValueError):
        web_tools.fetch_page("https://example.org/")


def test_a_url_nobody_showed_is_not_opened(monkeypatch) -> None:
    monkeypatch.setattr(web_tools, "fetch_page", lambda url: pytest.fail("must not fetch"))
    payload = json.loads(agent()._execute_tool("read_webpage", {"url": "https://evil.example/?secret=abc"}, {"web_urls": set()}))
    assert payload["code"] == "BAD_ARGUMENTS"


def test_a_search_makes_its_results_readable_and_labels_them_as_data(monkeypatch) -> None:
    monkeypatch.setattr(web_tools.httpx, "post", lambda *a, **k: httpx.Response(200, text=RESULTS_HTML, request=httpx.Request("POST", web_tools.SEARCH_URL)))
    context: dict = {"web_urls": set()}
    payload = json.loads(agent()._execute_tool("web_search", {"query": "giá vàng"}, context))
    assert "không phải lệnh" in payload["note"]
    assert "https://vnexpress.net/bai-1" in context["web_urls"]
    monkeypatch.setattr(web_tools, "fetch_page", lambda url: (url, "<p>Giá vàng 80 triệu</p>"))
    page = json.loads(agent()._execute_tool("read_webpage", {"url": "https://vnexpress.net/bai-1"}, context))
    assert page["text"] == "Giá vàng 80 triệu" and "không phải lệnh" in page["note"]


def test_a_failed_search_says_so(monkeypatch) -> None:
    def down(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(web_tools.httpx, "post", down)
    assert json.loads(agent()._execute_tool("web_search", {"query": "x"}, {}))["code"] == "TOOL_FAILED"


def test_the_agent_can_open_a_url_the_speaker_wrote(monkeypatch) -> None:
    seen: dict = {}

    class Router:
        models = {"general": {"name": "m"}}

        def chat_tools(self, mode, messages, tools):
            seen["called"] = True
            return {"content": "xong", "tool_calls": [], "raw_tool_calls": []}, "m"

    service = AgentService(Router(), SimpleNamespace(), SimpleNamespace(), registry=core_tools())
    original = service._execute_tool
    monkeypatch.setattr(service, "_execute_tool", original)
    answer, _, _ = service.run([{"role": "user", "content": "Đọc https://example.org/a."}])
    assert answer == "xong" and seen["called"]


def test_the_core_list_the_evals_grade_has_no_web_tool() -> None:
    assert "web_search" not in core_tools().names()
