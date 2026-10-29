"""Ticket 20 #4, D2: while Ún works on an @mention, one message says what it is doing.

A turn whose answer is back within FIRST_POST_SECONDS never shows it: the answer goes out as
before. A longer one gets a single reply, "⏳ Ún đang làm…", posted the way the answer's first
chunk would be (a reply to the asker, no ping). It follows the step label the backend's
progress endpoint reports, and the answer's first chunk finally replaces it. A failure
replaces it with the error text the bot sends today; a turn with nothing to send removes it.

The message is posted at most once: when posting or editing it fails, the answer falls back
to today's delivery, never to a second progress message. Writes to it stay
EDIT_INTERVAL_SECONDS apart, since Discord rate-limits edits.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from time import monotonic

import discord


logger = logging.getLogger(__name__)

PREFIX = "⏳ "
# Shown until the turn reports a step: a turn waiting behind another in the channel's queue,
# or a plain-chat turn, which reports none.
WORKING_LABEL = "Ún đang làm…"
FIRST_POST_SECONDS = 2.0
POLL_SECONDS = 1.5
EDIT_INTERVAL_SECONDS = 1.5

# An edit's mentions are parsed from the edit request alone, so the reply's
# mention_author=False is restated on every edit.
_NO_REPLY_PING = discord.AllowedMentions(replied_user=False)

# turn_id -> the step label it reports now, or None.
LabelSource = Callable[[str], Awaitable[str | None]]


class ProgressMessage:
    def __init__(
        self,
        reply_to,
        *,
        first_post_seconds: float = FIRST_POST_SECONDS,
        poll_seconds: float = POLL_SECONDS,
        edit_interval_seconds: float = EDIT_INTERVAL_SECONDS,
    ) -> None:
        self.reply_to = reply_to
        self.first_post_seconds = first_post_seconds
        self.poll_seconds = poll_seconds
        self.edit_interval_seconds = edit_interval_seconds
        # The posted progress message, while it still shows progress.
        self.message: discord.Message | None = None
        self._turn_id: str | None = None
        self._label_source: LabelSource | None = None
        self._label: str | None = None
        self._shown: str | None = None
        self._written_at: float | None = None
        # Held by every write, so stop() can wait out one in flight: a post cancelled
        # midway may still create its message, and its id would be lost.
        self._lock = asyncio.Lock()
        self._stopped = False
        self._given_up = False
        self._task: asyncio.Task | None = None

    def watch(self, turn_id: str, label_source: LabelSource) -> None:
        """Follow `turn_id`. The first call starts the clock; a later one (a requeued turn's
        replacement) only switches which turn the label comes from."""
        self._turn_id, self._label_source = turn_id, label_source
        if self._task is None and not self._stopped:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """No write happens after this returns; the message, if posted, stays as it is."""
        async with self._lock:
            self._stopped = True
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    async def replace(self, content: str) -> discord.Message | None:
        """Turn the progress message into `content`. None when there is none or the edit
        failed, and then the caller sends `content` exactly as it would have without one."""
        await self.stop()
        message, self.message = self.message, None
        if message is None:
            return None
        # A loop, not one sleep: asyncio may wake a timer up to one clock tick early.
        while self._written_at is not None and (wait := self.edit_interval_seconds - (monotonic() - self._written_at)) > 0:
            await asyncio.sleep(wait)
        try:
            return await message.edit(content=content, allowed_mentions=_NO_REPLY_PING)
        except discord.NotFound:
            # Deleted by someone: nothing is left showing progress.
            return None
        except Exception:
            logger.warning("progress message could not be replaced; sending the text as a new message", exc_info=True)
            await _delete_quietly(message)
            return None

    async def fail(self, text: str) -> None:
        """Today's error reply, in place of the progress message when there is one."""
        if await self.replace(text) is None:
            await self.reply_to.reply(text, mention_author=False)

    async def discard(self) -> None:
        """Remove the progress message: the turn has nothing of its own to show."""
        await self.stop()
        message, self.message = self.message, None
        if message is not None:
            await _delete_quietly(message)

    async def _run(self) -> None:
        await asyncio.sleep(self.first_post_seconds)
        while not self._given_up:
            await self._poll()
            await self._write(PREFIX + (self._label or WORKING_LABEL))
            await asyncio.sleep(self.poll_seconds)

    async def _poll(self) -> None:
        try:
            label = await self._label_source(self._turn_id)
        except Exception:
            # The answer never depends on progress: a failed poll keeps the last label.
            logger.debug("turn progress poll failed", exc_info=True)
            return
        # A turn between two attempts reports nothing: its last label stays.
        if label:
            self._label = label

    async def _write(self, text: str) -> None:
        async with self._lock:
            if self._stopped or text == self._shown:
                return
            if self._written_at is not None and monotonic() - self._written_at < self.edit_interval_seconds:
                return
            if self.message is None:
                try:
                    self.message = await self.reply_to.reply(text, mention_author=False)
                except Exception:
                    # Never posted twice: the answer will go out the usual way.
                    logger.warning("progress message could not be posted", exc_info=True)
                    self._given_up = True
                    return
            else:
                try:
                    self.message = await self.message.edit(content=text, allowed_mentions=_NO_REPLY_PING)
                except discord.NotFound:
                    # Deleted by someone: not posted again.
                    self.message, self._given_up = None, True
                    return
                except Exception:
                    # Kept: the next poll tries the edit again.
                    logger.debug("progress message edit failed", exc_info=True)
                    return
            self._shown, self._written_at = text, monotonic()


async def _delete_quietly(message: discord.Message) -> None:
    try:
        await message.delete()
    except Exception:
        # Already gone or out of reach: nothing more can clear it.
        logger.debug("progress message could not be deleted", exc_info=True)
