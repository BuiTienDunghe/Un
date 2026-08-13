from __future__ import annotations

from types import SimpleNamespace

import discord
import pytest

from discord_bot.session_location import (
    UnsupportedDiscordLocationError,
    canonical_discord_location,
)


def channel(channel_id: int, channel_type: discord.ChannelType, parent_id: int | None = None):
    return SimpleNamespace(id=channel_id, type=channel_type, parent_id=parent_id)


@pytest.mark.parametrize("channel_type", [discord.ChannelType.text, discord.ChannelType.news])
def test_text_and_announcement_channels_use_the_channel(channel_type):
    location = canonical_discord_location(
        SimpleNamespace(id=10),
        channel(20, channel_type),
    )
    assert location.guild_id == "10"
    assert location.channel_id == "20"
    assert location.thread_id is None


@pytest.mark.parametrize(
    "channel_type",
    [discord.ChannelType.public_thread, discord.ChannelType.private_thread],
)
def test_public_and_private_threads_use_parent_and_thread(channel_type):
    location = canonical_discord_location(
        SimpleNamespace(id=10),
        channel(30, channel_type, parent_id=20),
    )
    assert location.guild_id == "10"
    assert location.channel_id == "20"
    assert location.thread_id == "30"


def test_forum_post_is_canonicalized_as_a_thread():
    forum_post = channel(31, discord.ChannelType.public_thread, parent_id=21)
    location = canonical_discord_location(SimpleNamespace(id=11), forum_post)
    assert location.guild_id == "11"
    assert location.channel_id == "21"
    assert location.thread_id == "31"


def test_dm_and_parentless_thread_are_unsupported():
    with pytest.raises(UnsupportedDiscordLocationError):
        canonical_discord_location(None, channel(20, discord.ChannelType.private))
    with pytest.raises(UnsupportedDiscordLocationError):
        canonical_discord_location(
            SimpleNamespace(id=10),
            channel(30, discord.ChannelType.public_thread),
        )
