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
    return parts


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
