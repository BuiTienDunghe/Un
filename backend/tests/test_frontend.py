"""The web pages are served, and T8's shared helper file stays shared."""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

NODE = shutil.which("node")

FRONTEND = Path(__file__).resolve().parents[1] / "app" / "frontend"
PAGES = {"index.html": "app.js", "dashboard.html": "dashboard.js", "ocr.html": "ocr.js", "chunks.html": "chunks.js"}

#: Top-level declarations that land in the shared global scope of a classic
#: script. `var` and `async function` are in the list because an adversarial
#: pass walked both straight past the first version of this pattern — and they
#: fail differently: `var $` kills the page outright, while a second
#: `async function requestJson` is legal JS that SILENTLY overrides the shared
#: helper, which is exactly the drift T8 exists to end.
DECLARATION = re.compile(r"^(?:async\s+)?(?:const|let|var|function|class)\s+(\$|[A-Za-z_][\w$]*)", re.MULTILINE)


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
    """T8's guard, fast path: names the offender so the fix is obvious.

    Four pages each kept their own `$`, `el`, theme block and auth-header
    builder, and the four copies drifted — the dashboard's lost `X-API-Key`
    entirely, then lost token refresh, and fixing one copy fixed nothing else.

    This is a TEXTUAL check and it is deliberately not the last word: an
    adversarial pass got `var $`, an indented `  const $` and
    `async function requestJson` past it, each of which still kills the page.
    The test below is the one that cannot be fooled; this one exists because
    "dashboard.js redeclares ['$']" is a better error message than a parser
    dump, and it catches the way the fork actually comes back.
    """
    clashes = declared_names(script) & declared_names("common.js")

    assert not clashes, f"{script} redeclares {sorted(clashes)} — use the shared copy in common.js"


@pytest.mark.skipif(NODE is None, reason="needs node to parse")
@pytest.mark.parametrize("script", PAGES.values())
def test_common_js_and_each_page_survive_sharing_one_global_scope(script):
    """The guard that asks the engine instead of a regex.

    Two classic scripts on one page share the global lexical environment, so a
    name declared with const/let/class in common.js and re-declared in ANY form
    by the page throws during GlobalDeclarationInstantiation — before a single
    statement of the page script runs. Confirmed in real Chrome: the page then
    installs zero of dashboard.js's 19 top-level functions and renders as an
    inert shell. Per-file `node --check` (what CI's static job runs) exits 0 on
    every one of those variants, because the collision only exists in the pair.

    Concatenating the two files reproduces exactly the same scope rules, so
    this catches `var`, indentation and `async function` — all three of which
    walk straight past the textual check above.
    """
    merged = "\n".join(((FRONTEND / "common.js").read_text(encoding="utf-8"), (FRONTEND / script).read_text(encoding="utf-8")))
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
        handle.write(merged)
        probe = Path(handle.name)
    try:
        result = subprocess.run([NODE, "--check", str(probe)], capture_output=True, text=True)
    finally:
        probe.unlink(missing_ok=True)

    assert result.returncode == 0, f"common.js + {script} cannot coexist on one page: {result.stderr}"


def test_the_secondary_pages_still_reach_401_refresh_through_the_shared_path():
    """Guards the win T8 actually delivered, which nothing else was watching.

    Before T8 only the chat page retried a 401 by refreshing; dashboard, ocr and
    chunks gave up with a valid refresh token sitting in localStorage. That is
    now true only because all three route through common.js — and a revert of
    one page's wrapper body would restore the old behaviour while every other
    test in this file stayed green.

    So pin the shape: exactly one refresh implementation, and no page holding a
    hand-rolled JSON fetch of its own. The raw-fetch budget below is the list of
    deliberate carve-outs — a call that genuinely cannot go through requestJson
    (an SSE stream, a blob download, or auth itself, which must not recurse).
    """
    everywhere = {name: (FRONTEND / name).read_text(encoding="utf-8") for name in ["common.js", *PAGES.values()]}

    assert sum(text.count("async function refreshAccessToken") for text in everywhere.values()) == 1
    assert "async function refreshAccessToken" in everywhere["common.js"]

    for script in ("dashboard.js", "ocr.js", "chunks.js"):
        assert "requestJson" in everywhere[script], f"{script} no longer uses the shared request path"

    budget = {"common.js": 2, "app.js": 3, "dashboard.js": 0, "ocr.js": 1, "chunks.js": 0}
    actual = {name: text.count("fetch(") for name, text in everywhere.items()}

    assert actual == budget, (
        f"raw fetch( sites moved: {actual} != {budget}. A new one bypasses authHeaders and the 401 refresh — "
        "route it through requestJson, or raise the budget here and say why in the diff."
    )
