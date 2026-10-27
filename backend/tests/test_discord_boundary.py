"""The core does not depend on Discord (ticket 22): Discord plugs into the core, never the reverse.

Two checks, both read without a database or a running service:

- Source: no module under app/ outside app/discord/ imports app.discord. main.py is the
  one place allowed to, because it wires the package in, and so is the one shim C2 left
  for the agent's search_history tool. Lazy imports inside functions count.
- Runtime: importing a core module in a fresh interpreter pulls in no Discord module.
  answer_grounding, memory_service and the web memory router load none. The agent still
  reaches the Discord history service through the shim until C4 moves search_history
  into the package; that one debt is named below and nothing else is tolerated.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
APP = BACKEND / "app"

# models.py imports it and the Discord models stay in the shared metadata (ticket 22, choice 2):
# a constants module the core owns, whatever its name says.
ALWAYS_ALLOWED = {"app.postgres.discord_memory_constants"}
# The agent's search_history tool, until C4 registers it from the Discord package and deletes the shim.
SHIM = "services/discord_history_service.py"
SEARCH_HISTORY_DEBT = {"app.services.discord_history_service", "app.discord", "app.discord.history_service"}
CORE_MODULES = {
    "app.services.answer_grounding": set(),
    "app.services.memory_service": set(),
    "app.routers.memory": set(),
    "app.services.agent_service": SEARCH_HISTORY_DEBT,
    "app.services.chat_service": SEARCH_HISTORY_DEBT,
    "app.services.rag_service": SEARCH_HISTORY_DEBT,
}


def imports_app_discord(tree: ast.AST) -> list[str]:
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [alias.name for alias in node.names if alias.name == "app.discord" or alias.name.startswith("app.discord.")]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if node.module == "app.discord" or node.module.startswith("app.discord."):
                found.append(node.module)
            elif node.module == "app" and any(alias.name == "discord" for alias in node.names):
                found.append("app.discord")
    return found


def test_no_core_module_imports_the_discord_package():
    offenders = {}
    for path in sorted(APP.rglob("*.py")):
        relative = path.relative_to(APP).as_posix()
        if relative in ("main.py", SHIM) or relative.startswith("discord/"):
            continue
        names = imports_app_discord(ast.parse(path.read_text(encoding="utf-8")))
        if names:
            offenders[relative] = names
    assert not offenders, f"core modules import app.discord: {offenders}"


def test_only_the_agent_uses_the_shim():
    shim = "app.services.discord_history_service"
    users = sorted(
        path.relative_to(BACKEND).as_posix()
        for path in BACKEND.rglob("*.py")
        if path.relative_to(BACKEND).parts[0] in ("app", "scripts", "tests") and path.name != Path(__file__).name
        and shim in path.read_text(encoding="utf-8")
    )
    assert users == ["app/services/agent_service.py"], f"{shim} is the agent's alone until C4: {users}"


def test_the_source_check_sees_every_spelling_of_the_import():
    source = "import app.discord\nfrom app.discord.agent_tools import x\nfrom app import discord\ndef f():\n    import app.discord.workers\n"
    assert imports_app_discord(ast.parse(source)) == ["app.discord", "app.discord.agent_tools", "app.discord", "app.discord.workers"]
    assert imports_app_discord(ast.parse("import discord\nfrom app.services import memory_service\n")) == []


def discord_modules_loaded_by(module: str) -> set[str]:
    probe = ("import json, sys; import " + module + "; "
             "print(json.dumps(sorted(n for n in sys.modules if n.startswith('app.') and 'discord' in n)))")
    result = subprocess.run([sys.executable, "-c", probe], cwd=BACKEND, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr[-2000:]
    return set(json.loads(result.stdout.strip().splitlines()[-1]))


@pytest.mark.parametrize("module", sorted(CORE_MODULES))
def test_importing_a_core_module_loads_no_discord_module(module):
    unexpected = discord_modules_loaded_by(module) - ALWAYS_ALLOWED - CORE_MODULES[module]
    assert not unexpected, f"{module} loads {sorted(unexpected)}"
