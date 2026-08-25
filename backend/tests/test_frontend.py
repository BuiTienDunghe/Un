"""The web pages are served, and T8's shared helper file stays shared."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[1] / "app" / "frontend"
PAGES = {"index.html": "app.js", "dashboard.html": "dashboard.js", "ocr.html": "ocr.js", "chunks.html": "chunks.js"}

#: Top-level `const x`, `let x`, `function x`, `class x` — the declarations that
#: live in the shared global scope of a classic script.
DECLARATION = re.compile(r"^(?:const|let|function|class)\s+(\$|[A-Za-z_][\w$]*)", re.MULTILINE)


def declared_names(filename: str) -> set[str]:
    return set(DECLARATION.findall((FRONTEND / filename).read_text(encoding="utf-8")))


def test_frontend_is_served(client):
    response = client.get("/ui/")

    assert response.status_code == 200
    assert "Trợ lý AI" in response.text


def test_shared_helpers_are_served(client):
    response = client.get("/ui/common.js")

    assert response.status_code == 200
    assert "function authHeaders" in response.text


@pytest.mark.parametrize(("page", "script"), PAGES.items())
def test_every_page_loads_common_js_before_its_own_script(page, script):
    """Order is the contract: the page script uses names common.js declares."""
    html = (FRONTEND / page).read_text(encoding="utf-8")

    common_at, own_at = html.find("/ui/common.js"), html.find(f"/ui/{script}")

    assert common_at != -1, f"{page} does not load common.js"
    assert 0 <= common_at < own_at, f"{page} loads {script} before common.js"


@pytest.mark.parametrize("script", PAGES.values())
def test_no_page_redeclares_a_helper_that_common_js_owns(script):
    """T8's guard: this is what makes the fork stay dead.

    Four pages each kept their own `$`, `el`, theme block and auth-header
    builder, and the four copies drifted — the dashboard's lost `X-API-Key`
    entirely, then lost token refresh, and fixing one copy fixed nothing else.
    Two classic scripts sharing a global scope cannot both `const $ = ...`, so
    a redeclaration here is a real page-breaking error, not a style rule.
    """
    clashes = declared_names(script) & declared_names("common.js")

    assert not clashes, f"{script} redeclares {sorted(clashes)} — use the shared copy in common.js"
