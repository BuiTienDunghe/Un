from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from dataclasses import dataclass
from pathlib import Path

import discord
from discord import app_commands

from discord_bot.api_client import BackendClientError, BackendConversationNotFoundError, LocalAgentClient, LocalAgentSettings
from discord_bot.client import LocalAgentDiscordBot, split_for_discord


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DiscordSettings:
    token: str
    client_id: str
    invite_url: str
    local_agent: LocalAgentSettings
    system_prompt_path: Path
    member_context_limit: int

    @classmethod
    def from_env(cls) -> "DiscordSettings":
        token = os.environ.get("DISCORD_TOKEN", "").strip()
        if not token:
            raise RuntimeError("DISCORD_TOKEN is required.")
        return cls(
            token=token,
            client_id=os.environ.get("DISCORD_CLIENT_ID", "1522310732912398527"),
            invite_url=os.environ.get("DISCORD_INVITE_URL", "https://discord.com/oauth2/authorize?client_id=1522310732912398527"),
            local_agent=LocalAgentSettings(
                base_url=os.environ.get("LOCAL_AGENT_BASE_URL", "http://api:8000"),
                username=os.environ.get("LOCAL_AGENT_USERNAME", ""),
                password=os.environ.get("LOCAL_AGENT_PASSWORD", ""),
            ),
            system_prompt_path=Path(os.environ.get("DISCORD_SYSTEM_PROMPT_PATH", "discord_bot/system_prompt.md")),
            member_context_limit=max(0, min(int(os.environ.get("DISCORD_MEMBER_CONTEXT_LIMIT", "100")), 500)),
        )


def load_system_prompt(path: Path) -> str:
    try:
        prompt = path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise RuntimeError(f"Discord system prompt cannot be read: {path}") from error
    if not prompt:
        raise RuntimeError("Discord system prompt cannot be empty.")
    return prompt


def guild_context(guild: discord.Guild | None, member_limit: int) -> str:
    if guild is None:
        return "This conversation is in a direct message, not a Discord server."
    names = [member.display_name for member in guild.members if not member.bot][:member_limit]
    member_text = ", ".join(names) if names else "No member names are available in cache."
    suffix = "" if guild.member_count is None or len(names) >= guild.member_count else " Member names are truncated."
    return f"Discord server context: server name={guild.name!r}; member count={guild.member_count or 0}; visible non-bot member names={member_text}.{suffix}"


def conversation_key(guild_id: int | None, channel_id: int, user_id: int) -> str:
    raw = f"discord:{guild_id or 0}:{channel_id}:{user_id}".encode("utf-8")
    return f"discord_{hashlib.sha256(raw).hexdigest()[:48]}"


def create_bot(api_client: LocalAgentClient, system_prompt: str, member_context_limit: int) -> LocalAgentDiscordBot:
    bot = LocalAgentDiscordBot()
    conversations: dict[str, str] = {}

    def prompt_for(guild: discord.Guild | None) -> str:
        return f"{system_prompt}\n\n{guild_context(guild, member_context_limit)}"

    async def send_answer(channel, answer: str, *, reply_to: discord.Message | None = None) -> None:
        chunks = split_for_discord(answer)
        if reply_to is not None:
            await reply_to.reply(chunks[0], mention_author=False)
        else:
            await channel.send(chunks[0])
        for chunk in chunks[1:]:
            await channel.send(chunk)

    async def ask_backend(question: str, guild: discord.Guild | None, channel_id: int, user_id: int) -> str:
        key = conversation_key(guild.id if guild else None, channel_id, user_id)
        try:
            result = await api_client.ask_with_conversation(question, conversation_id=conversations.get(key), system_prompt=prompt_for(guild))
        except BackendConversationNotFoundError:
            # PostgreSQL may have been reset or retention may have removed an
            # old conversation. Drop only this mapping and let the backend
            # create a fresh conversation on the retry.
            conversations.pop(key, None)
            result = await api_client.ask_with_conversation(question, system_prompt=prompt_for(guild))
        conversations[key] = result.conversation_id
        return result.answer

    @bot.event
    async def on_ready() -> None:
        logger.info("Discord bot connected as %s (id=%s)", bot.user, getattr(bot.user, "id", "unknown"))

    @bot.tree.command(name="ping", description="Check that the Discord bot is responding.")
    async def ping(interaction):
        await interaction.response.send_message("Pong")

    @bot.tree.command(name="ask", description="Ask the Local AI Core backend.")
    @app_commands.describe(question="Question for the Local AI Core backend")
    async def ask(interaction, question: str):
        if len(question) > 10_000:
            await interaction.response.send_message("Question is too long (maximum 10,000 characters).", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        try:
            answer = await ask_backend(
                question,
                interaction.guild,
                interaction.channel_id,
                interaction.user.id,
            )
        except BackendClientError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return
        await send_answer(interaction.followup, answer)

    @bot.event
    async def on_message(message: discord.Message) -> None:
        if message.author.bot or bot.user is None or not bot.user.mentioned_in(message):
            return
        question = message.content.replace(f"<@{bot.user.id}>", "").replace(f"<@!{bot.user.id}>", "").strip()
        if not question:
            await message.reply("Hãy gắn kèm câu hỏi sau @Ún.", mention_author=False)
            return
        async with message.channel.typing():
            try:
                answer = await ask_backend(
                    question,
                    message.guild,
                    message.channel.id,
                    message.author.id,
                )
            except BackendClientError as error:
                await message.reply(str(error), mention_author=False)
                return
        await send_answer(message.channel, answer, reply_to=message)

    return bot


async def run() -> None:
    settings = DiscordSettings.from_env()
    api_client = LocalAgentClient(settings.local_agent)
    bot = create_bot(api_client, load_system_prompt(settings.system_prompt_path), settings.member_context_limit)
    try:
        # Never log settings.token or any password.
        logger.info("Starting Discord bot client_id=%s backend=%s", settings.client_id, settings.local_agent.base_url)
        await bot.start(settings.token)
    finally:
        await api_client.aclose()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
