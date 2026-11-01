"""The bot's half of approvals (ticket 46): Duyệt / Từ chối buttons on the answer that asks for a yes, and /approvals.

The bot decides nothing here. The backend keeps the call, knows whose it is, refuses a late or a second yes,
and runs the tool; the bot only relays a click. What it adds is manners: only the member the call belongs to can
press a button (anyone else is told so, privately, and nothing is sent), a button stops working once pressed or
once the time is up, the call is shown exactly as the model wrote it inside a code block (so `@everyone` in it is
text, not a ping), and no message here can mention anyone.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import discord

from discord_bot.api_client import BackendApproval, BackendApprovalDecision, BackendClientError, LocalAgentClient

logger = logging.getLogger(__name__)

APPROVE_LABEL = "Duyệt"
DENY_LABEL = "Từ chối"
# The words the backend's own reply carries (ApprovalService._notice). Only an answer with them is worth asking
# the backend about: every other answer costs no extra request. A model that writes them gets one harmless GET.
NOTICE_MARK = "Mã duyệt:"
RESULT_MAX_CHARS = 1_500
NOT_YOURS = "Chỉ người nhờ việc này bấm được."
ALREADY_PRESSED = "Việc này đã được bấm rồi."
NO_MENTIONS = discord.AllowedMentions.none()


def fenced(text: str) -> str:
    """The text in a code block it cannot close early, however many backticks it holds."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}\n{text}\n{fence}"


def _tool(name: str) -> str:
    return name.replace("`", "'")


def _deadline(approval: BackendApproval) -> datetime | None:
    try:
        moment = datetime.fromisoformat(approval.expires_at)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def seconds_left(approval: BackendApproval, now: datetime | None = None) -> float:
    deadline = _deadline(approval)
    if deadline is None:
        return 0.0
    return max(0.0, (deadline - (now or datetime.now(timezone.utc))).total_seconds())


def format_approval(approval: BackendApproval) -> str:
    """One waiting call, whole: the member must see what they would be approving."""
    deadline = _deadline(approval)
    until = f" · hết hạn <t:{int(deadline.timestamp())}:R>" if deadline is not None else ""
    return f"**Chờ bạn duyệt** `{approval.short_id}` · công cụ `{_tool(approval.tool_name)}`{until}\n{fenced(approval.arguments)}"


def format_decision(decision: BackendApprovalDecision) -> str:
    tool = _tool(decision.tool_name)
    if decision.status == "denied":
        return f"Đã từ chối `{tool}`. Mình không làm gì cả."
    shown = ""
    if decision.text:
        text = decision.text if len(decision.text) <= RESULT_MAX_CHARS else decision.text[: RESULT_MAX_CHARS - 1] + "…"
        shown = f"\n{fenced(text)}"
    if decision.status == "done":
        return f"Đã chạy `{tool}`.{shown}"
    code = f" (mã `{decision.code}`)" if decision.code else ""
    return f"`{tool}` chạy không thành công{code}.{shown}"


class ApprovalView(discord.ui.View):
    """The two buttons for one waiting call. They go quiet after the first press, and when the time is up."""

    def __init__(self, api_client: LocalAgentClient, approval: BackendApproval, *, timeout: float) -> None:
        super().__init__(timeout=max(1.0, timeout))
        self.api_client = api_client
        self.approval = approval
        # The message that carries the buttons, set by whoever sends it, so a timeout can switch them off.
        self.message = None
        self._pressed = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.approval.requester_id:
            await interaction.response.send_message(NOT_YOURS, ephemeral=True, allowed_mentions=NO_MENTIONS)
            return False
        return True

    @discord.ui.button(label=APPROVE_LABEL, style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._decide(interaction, approve=True)

    @discord.ui.button(label=DENY_LABEL, style=discord.ButtonStyle.danger)
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._decide(interaction, approve=False)

    def _switch_off(self) -> None:
        for item in self.children:
            item.disabled = True

    async def _decide(self, interaction: discord.Interaction, *, approve: bool) -> None:
        if self._pressed:
            # A second press while the first is still being sent: the backend would refuse it too.
            await interaction.response.send_message(ALREADY_PRESSED, ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        self._pressed = True
        self._switch_off()
        # Acknowledge inside Discord's three seconds; a tool can take longer than that to answer.
        await interaction.response.edit_message(view=self)
        try:
            decision = await self.api_client.decide_approval(
                self.approval.approval_id, self.approval.guild_id, str(interaction.user.id), approve=approve,
            )
        except BackendClientError as error:
            await interaction.followup.send(
                f"{error} Nếu việc này vẫn còn chờ, dùng /approvals để bấm lại.", ephemeral=True, allowed_mentions=NO_MENTIONS,
            )
        else:
            await interaction.followup.send(format_decision(decision), allowed_mentions=NO_MENTIONS)
        self.stop()

    async def on_timeout(self) -> None:
        if self._pressed or self.message is None:
            return
        self._switch_off()
        try:
            await self.message.edit(view=self)
        except Exception:
            logger.debug("approval buttons could not be switched off", exc_info=True)


async def offer_buttons(
    api_client: LocalAgentClient, message, *, guild_id: str, author_id: str, turn_id: str | None, answer: str,
) -> None:
    """Put the buttons on the answer of a turn that ended asking for a yes. Never raises: the answer is already
    out, and without buttons the member can still use /approvals."""
    if not turn_id or NOTICE_MARK not in answer:
        return
    try:
        waiting = [item for item in await api_client.list_approvals(guild_id, author_id) if item.source_turn_id == turn_id]
        if not waiting:
            return
        view = ApprovalView(api_client, waiting[0], timeout=seconds_left(waiting[0]))
        view.message = await message.edit(view=view, allowed_mentions=NO_MENTIONS) or message
    except Exception as error:
        logger.warning("approval buttons not attached: %s", type(error).__name__)
