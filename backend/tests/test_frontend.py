"""The web UI is one shell (index.html) loading classic scripts that share ONE global scope.

v2 (16/09/2026) replaced the four standalone pages with a hash-routed app: common.js →
components.js → router.js → shell.js → uploads.js → views/*.js, all `defer`, in that order.
The old pages survive only as redirects so links such as /ui/chunks.html?document_id= keep
working. What these tests pin is the part a browser would punish silently: load order, one
global scope with no name collisions, one refresh implementation, and no stray raw fetch.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

NODE = shutil.which("node")

FRONTEND = Path(__file__).resolve().parents[1] / "app" / "frontend"
INDEX = (FRONTEND / "index.html").read_text(encoding="utf-8")

#: Script tags in document order, as paths relative to the frontend folder.
SCRIPTS = [src for src in re.findall(r'<script[^>]*\ssrc="/ui/([^"?]+)(?:\?[^"]*)?"', INDEX)]
#: The screens the design handoff names (README "Kiến trúc đề xuất").
VIEWS = ["chat", "documents", "memory", "dashboard", "ocr", "bot", "models", "users", "settings", "chunks"]

#: Top-level declarations that land in the shared global scope of a classic script.
#: `var` and `async function` are in the list because an adversarial pass walked both
#: straight past the first version of this pattern — and they fail differently: `var $`
#: kills the page outright, while a second `async function requestJson` is legal JS that
#: SILENTLY overrides the shared helper.
DECLARATION = re.compile(r"^(?:async\s+)?(?:const|let|var|function|class)\s+(\$|[A-Za-z_][\w$]*)", re.MULTILINE)


def source(name: str) -> str:
    return (FRONTEND / name).read_text(encoding="utf-8")


def declared_names(name: str) -> set[str]:
    return set(DECLARATION.findall(source(name)))


def test_frontend_is_served(client):
    response = client.get("/ui/")

    assert response.status_code == 200
    assert "Trợ lý AI" in response.text


def test_shared_helpers_are_served(client):
    response = client.get("/ui/common.js")

    assert response.status_code == 200
    assert "function authHeaders" in response.text


def test_the_shell_loads_the_shared_layers_first_then_every_view():
    """Order is the contract: each layer uses names the layers before it declare."""
    assert SCRIPTS[:4] == ["common.js", "components.js", "router.js", "shell.js"], SCRIPTS
    views = [s for s in SCRIPTS if s.startswith("views/")]
    assert views == [f"views/{v}.js" for v in VIEWS], views
    assert SCRIPTS.index(views[0]) > SCRIPTS.index("shell.js")
    assert all(re.search(rf'<script[^>]*src="/ui/{re.escape(s)}[^"]*"[^>]*\sdefer', INDEX) for s in SCRIPTS), \
        "every script must be defer — defer is what keeps the order"
    for script in SCRIPTS:
        assert (FRONTEND / script).is_file(), f"index.html loads a missing file: {script}"


def test_every_view_stylesheet_is_linked():
    for view in VIEWS:
        assert (FRONTEND / "views" / f"{view}.css").is_file()
        assert f'href="/ui/views/{view}.css' in INDEX, f"views/{view}.css is not linked from index.html"


def test_every_screen_registers_its_route():
    for view in VIEWS:
        assert re.search(rf'Router\.register\(\s*["\']{view}["\']', source(f"views/{view}.js")), f"views/{view}.js does not register #/{view}"


@pytest.mark.parametrize(("page", "route"), [("dashboard.html", "#/dashboard"), ("ocr.html", "#/ocr"), ("chunks.html", "#/chunks/")])
def test_the_old_pages_are_redirects_to_their_hash_route(page, route):
    """Links from before v2 (bookmarks, the dashboard's old #c= links, chunks.html?document_id=)."""
    html = source(page)

    assert route in html
    assert "/ui/common.js" not in html, f"{page} is a redirect now; it must not boot a second app"


def test_chunks_redirect_carries_the_document_id():
    assert "document_id" in source("chunks.html")


@pytest.mark.parametrize("script", [s for s in SCRIPTS if s != "common.js"])
def test_no_script_redeclares_a_helper_that_common_js_owns(script):
    """T8's guard, fast path: names the offender so the fix is obvious.

    This is a TEXTUAL check and it is deliberately not the last word — see the engine
    test below, which cannot be fooled by indentation or `var`.
    """
    clashes = declared_names(script) & declared_names("common.js")

    assert not clashes, f"{script} redeclares {sorted(clashes)} — use the shared copy in common.js"


@pytest.mark.parametrize("view", VIEWS)
def test_views_keep_their_names_out_of_the_global_scope(view):
    """Ten views on one page: a top-level `const state` in two of them kills the second."""
    names = declared_names(f"views/{view}.js")

    assert not names, f"views/{view}.js declares {sorted(names)} at top level — wrap the file in an IIFE"


@pytest.mark.skipif(NODE is None, reason="needs node to parse")
def test_every_script_survives_sharing_one_global_scope():
    """The guard that asks the engine instead of a regex.

    Classic scripts on one page share the global lexical environment, so a name declared
    with const/let/class in one file and re-declared in ANY form by another throws during
    GlobalDeclarationInstantiation — before a single statement of the later file runs.
    Per-file `node --check` (what CI's static job runs) exits 0 on every such pair, because
    the collision only exists on the page. Concatenating in load order reproduces it.
    """
    merged = "\n;\n".join(source(script) for script in SCRIPTS)
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
        handle.write(merged)
        probe = Path(handle.name)
    try:
        result = subprocess.run([NODE, "--check", str(probe)], capture_output=True, text=True)
    finally:
        probe.unlink(missing_ok=True)

    assert result.returncode == 0, f"the scripts in index.html cannot coexist on one page: {result.stderr}"


def test_there_is_one_refresh_implementation_and_no_stray_raw_fetch():
    """Every JSON call goes through requestJson (via Shell.api), which owns the 401 refresh.

    The raw-fetch budget below is the list of deliberate carve-outs — a call that genuinely
    cannot go through requestJson: the refresh itself (common.js), a binary download with
    auth headers (Shell.fetchBlob), and the SSE chat stream (views/chat.js).
    """
    everywhere = {script: source(script) for script in SCRIPTS}

    assert sum(text.count("async function refreshAccessToken") for text in everywhere.values()) == 1
    assert "async function refreshAccessToken" in everywhere["common.js"]

    budget = {script: 0 for script in SCRIPTS}
    budget.update({"common.js": 2, "shell.js": 1, "views/chat.js": 1})
    actual = {script: text.count("fetch(") for script, text in everywhere.items()}

    assert actual == budget, (
        f"raw fetch( sites moved: {actual} != {budget}. A new one bypasses authHeaders and the 401 refresh — "
        "route it through Shell.api / Shell.fetchBlob, or raise the budget here and say why in the diff."
    )


def test_every_icon_the_code_asks_for_is_in_the_sprite():
    """A missing <symbol> renders as nothing at all — no error anywhere, just an empty button."""
    sprite = set(re.findall(r'<symbol[^>]*\sid="i-([\w-]+)"', INDEX))
    wanted: dict[str, str] = {}
    for script in SCRIPTS:
        for name in re.findall(r"""\bicon\(\s*["']([\w-]+)["']""", source(script)):
            wanted.setdefault(name, script)
    for name in re.findall(r'href="#i-([\w-]+)"', INDEX):
        wanted.setdefault(name, "index.html")

    missing = {name: where for name, where in wanted.items() if name not in sprite}

    assert not missing, f"icons used but not in the index.html sprite: {missing}"
