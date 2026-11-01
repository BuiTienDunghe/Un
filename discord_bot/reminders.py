"""Sending the reminders members asked for (ticket 48).

The bot decides nothing here. The backend says what is due and what to do with a late one; the
bot only delivers: to the channel the reminder came from, in a server still on the guild
allowlist, mentioning the member who made it and nobody else. Only a Discord refusal that cannot
change (channel deleted, no permission, wrong server) is reported as final; anything else is
reported as worth another try and the backend decides how many.
"""
from __future__ import annotations

import asyncio
import logging
from time import monotonic
from datetime import datetime, timedelta, timezone

import discord

from discord_bot.api_client import BackendClientError, BackendReminder, LocalAgentClient

logger = logging.getLogger(__name__)

POLL_SECONDS_DEFAULT = 30.0
LATE_NOTE_SECONDS = 300
ACK_ATTEMPTS = 3
# A receipt the backend would not take is offered again on every tick for this long: well past the
# backend's lease, so a backend that restarts or is down for a while still gets it before it re-issues the reminder.
RECEIPT_KEPT_SECONDS = 3600.0
VIETNAM_TIME = timezone(timedelta(hours=7))
_ZERO_WIDTH_SPACE = "​"


def neutralize_mentions(text: str) -> str:
    """Belt and braces next to allowed_mentions: whatever the text says, it cannot read as a ping."""
    for mention in ("@everyone", "@here"):
        text = text.replace(mention, f"@{_ZERO_WIDTH_SPACE}{mention[1:]}")
    return text.replace("<@", f"<{_ZERO_WIDTH_SPACE}@")


def human_delay(seconds: int) -> str:
    minutes = max(1, round(seconds / 60))
    if minutes < 60:
        return f"{minutes} phút"
    hours, rest = divmod(minutes, 60)
    return f"{hours} giờ {rest} phút" if rest else f"{hours} giờ"


def format_reminder(reminder: BackendReminder) -> str:
    message = f"<@{reminder.creator_id}> ⏰ Nhắc việc: {neutralize_mentions(reminder.text)}"
    if reminder.late_seconds >= LATE_NOTE_SECONDS:
        try:
            due = datetime.fromisoformat(reminder.due_at).astimezone(VIETNAM_TIME).strftime("%H:%M %d/%m")
        except ValueError:
            due = reminder.due_at
        message += f"\n_(Trễ {human_delay(reminder.late_seconds)}: hẹn lúc {due}, Ún chưa chạy lúc đó.)_"
    return message


def mention_only(creator_id: str) -> discord.AllowedMentions:
    return discord.AllowedMentions(everyone=False, roles=False, users=[discord.Object(id=int(creator_id))], replied_user=False)


def format_reminder_list(reminders: list[BackendReminder]) -> str:
    if not reminders:
        return "Bạn chưa có lời nhắc nào đang chờ trong server này."
    lines = [f"**{len(reminders)} lời nhắc của bạn:**"]
    for reminder in reminders:
        try:
            due = datetime.fromisoformat(reminder.due_at).astimezone(VIETNAM_TIME).strftime("%H:%M %d/%m")
        except ValueError:
            due = reminder.due_at
        state = " · lỡ giờ, Ún không gửi" if reminder.status == "missed" else ""
        lines.append(f"`{reminder.short_id}` · {due} · <#{reminder.channel_id}> · {neutralize_mentions(reminder.text)}{state}")
    lines.append("_Huỷ bằng `/reminders cancel` kèm mã ở đầu dòng._")
    return "\n".join(lines)


class ReminderSender:
    """One pass of delivery per tick(); run_forever() repeats it."""

    def __init__(
        self,
        bot: discord.Client,
        api_client: LocalAgentClient,
        guild_allowed,
        *,
        poll_seconds: float = POLL_SECONDS_DEFAULT,
    ) -> None:
        self.bot = bot
        self.api_client = api_client
        self.guild_allowed = guild_allowed
        self.poll_seconds = max(5.0, poll_seconds)
        # reminder id -> (Discord message id, when it was sent): sent, receipt not yet taken by the backend.
        self._unacknowledged: dict[str, tuple[str, float]] = {}

    async def run_forever(self) -> None:
        logger.info("Reminders are on: asking the backend every %.0f s", self.poll_seconds)
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                # Backend down or off: the reminders wait there and go out, late, when it is back.
                logger.warning("reminder poll failed: %s", type(error).__name__)
            await asyncio.sleep(self.poll_seconds)

    async def tick(self) -> int:
        sent = 0
        await self._retry_receipts()
        for reminder in await self.api_client.claim_reminders():
            if reminder.reminder_id in self._unacknowledged:
                # Handed out again because its receipt never arrived. It was sent; only the receipt is owed.
                await self._acknowledge(reminder.reminder_id)
                continue
            if await self.deliver(reminder):
                sent += 1
        return sent

    async def _channel(self, reminder: BackendReminder):
        channel_id = int(reminder.channel_id)
        return self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)

    async def deliver(self, reminder: BackendReminder) -> bool:
        if not self.guild_allowed(reminder.guild_id):
            await self._report(reminder, "guild_not_allowed", retryable=False)
            return False
        try:
            channel = await self._channel(reminder)
            if str(getattr(getattr(channel, "guild", None), "id", "")) != reminder.guild_id:
                await self._report(reminder, "channel_not_in_the_reminders_server", retryable=False)
                return False
            message = await channel.send(format_reminder(reminder), allowed_mentions=mention_only(reminder.creator_id))
        except (discord.NotFound, discord.Forbidden) as error:
            await self._report(reminder, f"discord_{type(error).__name__}", retryable=False)
            return False
        except Exception as error:
            await self._report(reminder, f"send_failed_{type(error).__name__}", retryable=True)
            return False
        # Discord has the message. From here the bot never sends it again: a receipt the backend does not
        # take is kept and offered on later ticks, and a re-issued reminder with a kept receipt is not sent.
        self._unacknowledged[reminder.reminder_id] = (str(message.id), monotonic())
        await self._acknowledge(reminder.reminder_id)
        return True

    async def _acknowledge(self, reminder_id: str, attempts: int = ACK_ATTEMPTS) -> None:
        message_id, _ = self._unacknowledged[reminder_id]
        for attempt in range(attempts):
            try:
                await self.api_client.reminder_sent(reminder_id, message_id)
            except BackendClientError:
                if attempt < attempts - 1:
                    await asyncio.sleep(0.1 * (attempt + 1))
                continue
            del self._unacknowledged[reminder_id]
            return
        logger.warning("reminder %s was sent but the receipt was not recorded; will offer it again", reminder_id[:8])

    async def _retry_receipts(self) -> None:
        for reminder_id, (_, sent_at) in list(self._unacknowledged.items()):
            if monotonic() - sent_at > RECEIPT_KEPT_SECONDS:
                del self._unacknowledged[reminder_id]
                logger.warning("reminder %s: gave up offering the receipt", reminder_id[:8])
            else:
                await self._acknowledge(reminder_id, attempts=1)

    async def _report(self, reminder: BackendReminder, error: str, *, retryable: bool) -> None:
        logger.warning("reminder %s not delivered: %s (retryable=%s)", reminder.short_id, error, retryable)
        try:
            await self.api_client.reminder_failed(reminder.reminder_id, error, retryable=retryable)
        except BackendClientError:
            logger.warning("reminder %s: the failure report did not reach the backend", reminder.short_id)
