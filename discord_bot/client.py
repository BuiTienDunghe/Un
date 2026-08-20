from __future__ import annotations

import discord


DISCORD_MESSAGE_LIMIT = 2_000
SAFE_MESSAGE_LIMIT = 1_900


def split_for_discord(message: str, limit: int = SAFE_MESSAGE_LIMIT) -> list[str]:
    """Split safely without exceeding Discord's 2,000-character message limit."""
    if not message:
        return ["(No response.)"]
    parts: list[str] = []
    remaining = message
    while len(remaining) > limit:
        split_at = remaining.rfind("\n", 0, limit + 1)
        if split_at < max(1, limit // 2):
            split_at = remaining.rfind(" ", 0, limit + 1)
        if split_at < 1:
            split_at = limit
        parts.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()
    parts.append(remaining)
    # Discord rejects empty/whitespace-only message content.
    cleaned = [part for part in parts if part.strip()]
    return cleaned or ["(No response.)"]


def escape_discord_markdown(text: str) -> str:
    """Filenames like sach_*ky-thuat*.pdf must render literally, not as italics."""
    for character in ("\\", "*", "_", "~", "`", "|"):
        text = text.replace(character, f"\\{character}")
    return text


def format_rag_sources(sources) -> str:
    """Compact citation footer mapping the answer's [Source n] markers to files.

    The answer cites positions ([Source 1]..[Source k]), so numbering must be
    preserved; several chunks of one document collapse into a single line that
    lists every index pointing at it ("[1,3] file.pdf · trang 5").
    """
    grouped: dict[tuple[str, int | None, int | None], list[int]] = {}
    for index, source in enumerate(sources, start=1):
        grouped.setdefault((source.filename, source.page_start, source.page_end), []).append(index)
    lines: list[str] = []
    for (filename, page_start, page_end), indices in grouped.items():
        entry = f"[{','.join(map(str, indices))}] {escape_discord_markdown(filename)}"
        if page_start is not None:
            if page_end is not None and page_end != page_start:
                entry += f" · trang {page_start}–{page_end}"
            else:
                entry += f" · trang {page_start}"
        lines.append(entry)
    if not lines:
        return ""
    return "**Nguồn:** " + lines[0] if len(lines) == 1 else "**Nguồn:**\n" + "\n".join(lines)


def format_agent_memories(memories) -> str:
    """Private `/memory` reply (P2-3): what the agent remembers about the
    invoking member in this guild, and who let each memory in."""
    if not memories:
        return "Agent chưa nhớ điều gì về bạn trong server này."
    lines = [f"**Agent đang nhớ {len(memories)} điều về bạn:**"]
    for order, memory in enumerate(memories, start=1):
        reviewer = "🤖 tự áp dụng" if memory.applied_by == "agent" else "👤 người duyệt"
        lines.append(
            f"{order}. {escape_discord_markdown(memory.canonical_fact)}"
            f" ({memory.memory_type} · v{memory.version} · {reviewer})"
        )
    lines.append("_Quản lý hoặc thu hồi trên dashboard của Local AI Core._")
    return "\n".join(lines)


HEALTH_ROWS = (
    ("postgres", "PostgreSQL"),
    ("redis", "Redis"),
    ("qdrant", "Qdrant"),
    ("ollama", "Ollama"),
    ("worker_memory", "Worker memory"),
    ("outbox_dispatcher", "Outbox"),
    ("backup", "Backup"),
)


def format_health(payload: dict) -> str:
    """Compact `/status` reply (P2-3) from the public /health payload."""
    overall = str(payload.get("status", "unknown"))
    lines = [f"{'✅' if overall == 'ok' else '⚠️'} **Local AI Core: {overall}**"]
    for key, label in HEALTH_ROWS:
        value = str(payload.get(key, "?"))
        mark = "✅" if value == "ok" else ("➖" if value in ("disabled", "not_configured") else "⚠️")
        entry = f"{mark} {label}: {value}"
        if key == "backup" and payload.get("backup_age_hours"):
            entry += f" · {payload['backup_age_hours']}h tuổi"
        lines.append(entry)
    return "\n".join(lines)


class LocalAgentDiscordBot(discord.Client):
    def __init__(self) -> None:
        # Guilds is non-privileged. Message content and members must also be
        # enabled in Discord Developer Portal for @mention chat/member context.
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(intents=intents)
        self.tree = discord.app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        await self.tree.sync()
