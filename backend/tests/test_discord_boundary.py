"""The core does not depend on Discord (ticket 22): Discord plugs into the core, never the reverse.

Three checks, all read without a database or a running service:

- Source: no module under app/ outside app/discord/ imports app.discord. main.py is the
  one place allowed to, because it wires the package in. Lazy imports inside functions
  count.
- Runtime: importing a core module in a fresh interpreter pulls in no Discord module. The
  agent, chat and RAG services load none since C4, which moved search_history into the
  package (app/discord/agent_tools.py) and deleted the shim C2 had left for it.
- Settings (ticket 25, choice 1B): the discord_* fields of the shared Settings belong to the
  Discord package. Outside app/discord/, a module may read one only if the (module, field)
  pair is on a fixed list, so the core cannot start leaning on new Discord knobs unnoticed.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.config.settings import Settings

BACKEND = Path(__file__).resolve().parents[1]
APP = BACKEND / "app"

# models.py imports it and the Discord models stay in the shared metadata (ticket 22, choice 2):
# a constants module the core owns, whatever its name says.
ALWAYS_ALLOWED = {"app.postgres.discord_memory_constants"}
# Gone in C4: the agent's search_history tool now lives in app/discord/agent_tools.py.
SHIM = "services/discord_history_service.py"
CORE_MODULES = {
    "app.services.answer_grounding": set(),
    "app.services.memory_service": set(),
    "app.routers.memory": set(),
    "app.services.agent_service": set(),
    "app.services.chat_service": set(),
    "app.services.rag_service": set(),
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
        if relative == "main.py" or relative.startswith("discord/"):
            continue
        names = imports_app_discord(ast.parse(path.read_text(encoding="utf-8")))
        if names:
            offenders[relative] = names
    assert not offenders, f"core modules import app.discord: {offenders}"


def test_the_shim_is_gone_and_nothing_names_it():
    shim = "app.services.discord_history_service"
    assert not (APP / SHIM).exists()
    users = sorted(
        path.relative_to(BACKEND).as_posix()
        for path in BACKEND.rglob("*.py")
        if path.relative_to(BACKEND).parts[0] in ("app", "scripts", "tests") and path.name != Path(__file__).name
        and shim in path.read_text(encoding="utf-8")
    )
    assert users == [], f"{shim} was deleted in C4, yet these still name it: {users}"


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


# Ticket 25, choice 1B: the reads of discord_* settings the core still makes, as (path under app/, field),
# counted on main 0cc0e68: 7 fields, 8 pairs, 3 modules. Exactly today's reads: a new pair fails, and so
# does a listed pair whose read is gone, so the list always says what the core reads.
CORE_DISCORD_SETTINGS_READS = {
    # overrides_from_settings: the extractor/verifier tag pins, and which roles are switched off.
    ("config/model_registry.py", "discord_condensation_enabled"),
    ("config/model_registry.py", "discord_memory_extractor_enabled"),
    ("config/model_registry.py", "discord_memory_extractor_model"),
    ("config/model_registry.py", "discord_memory_verifier_enabled"),
    ("config/model_registry.py", "discord_memory_verifier_model"),
    # The memory queue's name for the job queue and /health, and the ingestion flag /health reports.
    ("main.py", "discord_memory_ingestion_enabled"),
    ("main.py", "discord_memory_queue_name"),
    ("workers/tasks.py", "discord_memory_queue_name"),
}
DISCORD_SETTINGS_FIELDS = frozenset(name for name in Settings.model_fields if name.startswith("discord_"))


def _built_from_discord_prefix(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.startswith("discord_")


def discord_settings_reads(tree: ast.AST, fields: frozenset[str] | set[str]) -> list[tuple[str, int]]:
    """(field, line) for each way a module can name a discord_* settings field: an attribute on any
    object (settings.x, self._settings.x, request.app.state.settings.x), a string equal to the name
    (getattr(settings, "x"), model_dump()["x"]), and a name built at run time from a "discord_" piece
    (f"discord_{x}", "discord_" + x), which no list could vouch for, so it is reported as such."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in fields:
            found.append((node.attr, node.lineno))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in fields:
            found.append((node.value, node.lineno))
        elif (isinstance(node, ast.JoinedStr) and node.values and _built_from_discord_prefix(node.values[0])) or (
            isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add) and _built_from_discord_prefix(node.left)
        ):
            found.append(("<name built at run time from 'discord_'>", node.lineno))
    return found


def test_core_modules_read_only_the_listed_discord_settings():
    found: dict[tuple[str, str], list[int]] = {}
    for path in sorted(APP.rglob("*.py")):
        relative = path.relative_to(APP).as_posix()
        # settings.py declares the fields and validates them; main.py is not exempt here.
        if relative.startswith("discord/") or relative == "config/settings.py":
            continue
        for field, line in discord_settings_reads(ast.parse(path.read_text(encoding="utf-8")), DISCORD_SETTINGS_FIELDS):
            found.setdefault((relative, field), []).append(line)
    new = {pair: lines for pair, lines in sorted(found.items()) if pair not in CORE_DISCORD_SETTINGS_READS}
    gone = sorted(CORE_DISCORD_SETTINGS_READS - set(found))
    assert not new, (
        f"core modules read discord_* settings that are not on ticket 25's list: {new}. Read the setting "
        "inside app/discord/ and hand the core the value, or, if the core truly needs it, add the pair "
        "to CORE_DISCORD_SETTINGS_READS and say why in the commit."
    )
    assert not gone, f"these listed reads are gone from the code; delete them from CORE_DISCORD_SETTINGS_READS: {gone}"


def test_the_settings_check_sees_every_spelling_of_a_read():
    fields = {"discord_x", "discord_y"}
    source = (
        "a = settings.discord_x\n"
        "b = request.app.state.settings.discord_y\n"
        "c = getattr(get_settings(), 'discord_x', None)\n"
        "d = settings.model_dump()['discord_y']\n"
        "e = getattr(settings, f'discord_{name}')\n"
        "f = getattr(settings, 'discord_' + name)\n"
        "def g(self):\n    return self._settings.discord_y\n"
    )
    built = "<name built at run time from 'discord_'>"
    assert sorted(discord_settings_reads(ast.parse(source), fields), key=lambda read: read[1]) == [
        ("discord_x", 1), ("discord_y", 2), ("discord_x", 3), ("discord_y", 4), (built, 5), (built, 6), ("discord_y", 8),
    ]
    # Not settings reads: an ORM column, a job type that only starts like a field, an env var name,
    # and a log line that mentions a field after other text.
    negatives = "turn.discord_message_id\nJOB = 'discord_x_ingest'\nDISCORD_X = 'DISCORD_X'\nlog(f'{n} discord_x')\n"
    assert discord_settings_reads(ast.parse(negatives), fields) == []
