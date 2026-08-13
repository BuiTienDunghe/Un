from __future__ import annotations

from dataclasses import dataclass

import discord


class UnsupportedDiscordLocationError(ValueError):
    pass


@dataclass(frozen=True)
class CanonicalDiscordLocation:
    guild_id: str
    channel_id: str
    thread_id: str | None


_THREAD_TYPES = {
    discord.ChannelType.public_thread,
    discord.ChannelType.private_thread,
    discord.ChannelType.news_thread,
}


def canonical_discord_location(guild, channel) -> CanonicalDiscordLocation:
    """Return the one canonical channel/thread/forum key used by the bot."""
    if guild is None:
        raise UnsupportedDiscordLocationError("Discord direct messages are not supported.")
    if channel is None or getattr(channel, "id", None) is None:
        raise UnsupportedDiscordLocationError("Discord channel is unavailable.")

    channel_type = getattr(channel, "type", None)
    is_thread = isinstance(channel, discord.Thread) or channel_type in _THREAD_TYPES
    if is_thread:
        parent_id = getattr(channel, "parent_id", None)
        if parent_id is None:
            parent = getattr(channel, "parent", None)
            parent_id = getattr(parent, "id", None)
        if parent_id is None:
            raise UnsupportedDiscordLocationError("Discord thread has no valid parent channel.")
        return CanonicalDiscordLocation(
            guild_id=str(guild.id),
            channel_id=str(parent_id),
            thread_id=str(channel.id),
        )

    return CanonicalDiscordLocation(
        guild_id=str(guild.id),
        channel_id=str(channel.id),
        thread_id=None,
    )
