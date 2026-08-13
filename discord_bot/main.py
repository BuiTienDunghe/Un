from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from time import monotonic

import discord
from discord import app_commands

from discord_bot.api_client import (
    BackendClientError,
    BackendConversationNotFoundError,
    BackendTimeoutError,
    BackendUnavailableError,
    LocalAgentClient,
    LocalAgentSettings,
)
from discord_bot.client import LocalAgentDiscordBot, split_for_discord
from discord_bot.session_location import (
    UnsupportedDiscordLocationError,
    canonical_discord_location,
)


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
    persistent_sessions_enabled: bool = False

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
                timeout_seconds=max(
                    1.0,
                    float(os.environ.get("DISCORD_BACKEND_TIMEOUT_SECONDS", "45")),
                ),
                turn_execute_timeout_seconds=max(
                    1.0,
                    float(
                        os.environ.get(
                            "DISCORD_TURN_EXECUTE_TIMEOUT_SECONDS",
                            "180",
                        )
                    ),
                ),
            ),
            system_prompt_path=Path(os.environ.get("DISCORD_SYSTEM_PROMPT_PATH", "discord_bot/system_prompt.md")),
            member_context_limit=max(0, min(int(os.environ.get("DISCORD_MEMBER_CONTEXT_LIMIT", "100")), 500)),
            persistent_sessions_enabled=os.environ.get(
                "DISCORD_PERSISTENT_SESSIONS_ENABLED",
                "false",
            ).strip().lower() in {"1", "true", "yes", "on"},
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


def discord_author_metadata(author) -> tuple[str, str]:
    """Read stable identity and display snapshot from the Discord object."""
    return str(author.id), str(author.display_name)


def discord_reply_message_id(message: discord.Message) -> str | None:
    reference = getattr(message, "reference", None)
    message_id = getattr(reference, "message_id", None)
    return str(message_id) if message_id is not None else None


@dataclass(frozen=True)
class PreparedDiscordAnswer:
    answer: str
    turn_id: str | None = None
    execution_token: str | None = None


async def send_discord_answer(
    channel,
    answer: str,
    *,
    reply_to: discord.Message | None = None,
) -> list[discord.Message]:
    """Send every response chunk once and retain Discord's returned objects."""

    chunks = split_for_discord(answer)
    sent: list[discord.Message] = []
    if reply_to is not None:
        sent.append(await reply_to.reply(chunks[0], mention_author=False))
    else:
        sent.append(await channel.send(chunks[0]))
    for chunk in chunks[1:]:
        sent.append(await channel.send(chunk))
    return sent


class DiscordConversationGateway:
    """Feature-gated bridge; the legacy RAM path remains the default."""

    def __init__(
        self,
        api_client: LocalAgentClient,
        system_prompt: str,
        member_context_limit: int,
        persistent_sessions_enabled: bool,
        poll_budget_seconds: float | None = None,
    ) -> None:
        self.api_client = api_client
        self.system_prompt = system_prompt
        self.member_context_limit = member_context_limit
        self.persistent_sessions_enabled = persistent_sessions_enabled
        # Waiting behind earlier FIFO turns must survive at least one full
        # model execution, so the budget follows the execute timeout.
        self.poll_budget_seconds = (
            poll_budget_seconds
            if poll_budget_seconds is not None
            else float(
                getattr(
                    getattr(api_client, "settings", None),
                    "turn_execute_timeout_seconds",
                    180.0,
                )
            )
        )
        self.conversations: dict[str, str] = {}

    def prompt_for(self, guild: discord.Guild | None) -> str:
        system_prompt = self.system_prompt
        member_context_limit = self.member_context_limit
        return f"{system_prompt}\n\n{guild_context(guild, member_context_limit)}"

    async def prepare(
        self,
        question: str,
        guild: discord.Guild | None,
        channel,
        user_id: int,
        author_display_name: str,
        discord_message_id: str,
        reply_to_discord_message_id: str | None = None,
    ) -> PreparedDiscordAnswer | None:
        if not self.persistent_sessions_enabled:
            key = conversation_key(guild.id if guild else None, channel.id, user_id)
            try:
                result = await self.api_client.ask_with_conversation(
                    question,
                    conversation_id=self.conversations.get(key),
                    system_prompt=self.prompt_for(guild),
                )
            except BackendConversationNotFoundError:
                self.conversations.pop(key, None)
                result = await self.api_client.ask_with_conversation(
                    question,
                    system_prompt=self.prompt_for(guild),
                )
            self.conversations[key] = result.conversation_id
            return PreparedDiscordAnswer(result.answer)

        try:
            location = canonical_discord_location(guild, channel)
        except UnsupportedDiscordLocationError as error:
            raise BackendClientError(str(error)) from error
        session = await self.api_client.resolve_discord_session(
            location.guild_id,
            location.channel_id,
            location.thread_id,
        )
        turn = await self.api_client.enqueue_discord_turn(
            session.session_id,
            discord_message_id,
            question,
            author_id=str(user_id),
            author_display_name=author_display_name,
            reply_to_discord_message_id=reply_to_discord_message_id,
            system_prompt=self.prompt_for(guild),
        )
        turn_id = turn.turn_id
        deadline = monotonic() + self.poll_budget_seconds
        while True:
            execution = await self.api_client.execute_discord_turn(turn_id)
            if execution.status == "requeued" and execution.replacement_turn_id:
                turn_id = execution.replacement_turn_id
                if monotonic() >= deadline:
                    break
                continue
            if (
                execution.status == "running"
                and execution.answer
                and execution.execution_token
            ):
                return PreparedDiscordAnswer(
                    execution.answer,
                    execution.turn_id,
                    execution.execution_token,
                )
            if execution.status == "completed":
                # An idempotent duplicate delivery has already been handled.
                return None
            if execution.status in {"failed", "cancelled"}:
                raise BackendClientError(
                    f"Discord turn ended with status {execution.status}."
                )
            if monotonic() >= deadline:
                break
            await asyncio.sleep(0.5)
        raise BackendClientError("Discord turn did not become ready before the polling deadline.")

    async def delivered(
        self,
        prepared: PreparedDiscordAnswer,
        discord_response_message_ids: list[str],
    ) -> None:
        if prepared.turn_id and prepared.execution_token:
            # Discord has already accepted the messages. Retry only the
            # idempotent backend acknowledgement; never send Discord content
            # again merely because the completion response was lost.
            for attempt in range(3):
                try:
                    await self.api_client.complete_discord_turn(
                        prepared.turn_id,
                        prepared.execution_token,
                        discord_response_message_ids,
                    )
                    return
                except (BackendTimeoutError, BackendUnavailableError):
                    if attempt == 2:
                        raise
                    await asyncio.sleep(0.1 * (attempt + 1))

    async def delivery_failed(
        self,
        prepared: PreparedDiscordAnswer,
        error: str,
        *,
        retryable: bool,
    ) -> None:
        if prepared.turn_id and prepared.execution_token:
            await self.api_client.fail_discord_turn(
                prepared.turn_id,
                prepared.execution_token,
                error,
                retryable=retryable,
            )


def create_bot(
    api_client: LocalAgentClient,
    system_prompt: str,
    member_context_limit: int,
    persistent_sessions_enabled: bool = False,
) -> LocalAgentDiscordBot:
    bot = LocalAgentDiscordBot()
    gateway = DiscordConversationGateway(
        api_client,
        system_prompt,
        member_context_limit,
        persistent_sessions_enabled,
    )

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
            author_id, author_display_name = discord_author_metadata(
                interaction.user
            )
            prepared = await gateway.prepare(
                question,
                interaction.guild,
                interaction.channel,
                int(author_id),
                author_display_name,
                str(interaction.id),
            )
        except BackendClientError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return
        if prepared is None:
            return
        try:
            sent_messages = await send_discord_answer(
                interaction.followup,
                prepared.answer,
            )
        except discord.NotFound:
            await gateway.delivery_failed(
                prepared,
                "Discord interaction was deleted or no longer exists.",
                retryable=False,
            )
            return
        except Exception as error:
            await gateway.delivery_failed(
                prepared,
                f"Discord delivery failed: {type(error).__name__}",
                retryable=True,
            )
            raise
        await gateway.delivered(
            prepared,
            [str(message.id) for message in sent_messages],
        )

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
                author_id, author_display_name = discord_author_metadata(
                    message.author
                )
                prepared = await gateway.prepare(
                    question,
                    message.guild,
                    message.channel,
                    int(author_id),
                    author_display_name,
                    str(message.id),
                    discord_reply_message_id(message),
                )
            except BackendClientError as error:
                await message.reply(str(error), mention_author=False)
                return
        if prepared is None:
            return
        try:
            sent_messages = await send_discord_answer(
                message.channel,
                prepared.answer,
                reply_to=message,
            )
        except discord.NotFound:
            await gateway.delivery_failed(
                prepared,
                "Discord source message was deleted before response delivery.",
                retryable=False,
            )
            return
        except Exception as error:
            await gateway.delivery_failed(
                prepared,
                f"Discord delivery failed: {type(error).__name__}",
                retryable=True,
            )
            raise
        await gateway.delivered(
            prepared,
            [str(sent_message.id) for sent_message in sent_messages],
        )

    return bot


async def run() -> None:
    settings = DiscordSettings.from_env()
    api_client = LocalAgentClient(settings.local_agent)
    bot = create_bot(
        api_client,
        load_system_prompt(settings.system_prompt_path),
        settings.member_context_limit,
        settings.persistent_sessions_enabled,
    )
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
