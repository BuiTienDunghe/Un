"""Read-only aggregate statistics for the management dashboard.

Web-agent numbers come from the auxiliary store (which already excludes
Discord-origin conversations); Discord-agent numbers are aggregated straight
from the session/turn/delivery tables. Everything here is read-only.
"""
from fastapi import APIRouter, Request
from sqlalchemy import func, select

from app.postgres.models import (
    DiscordConversationSession,
    DiscordSessionTurn,
    DiscordTurnDelivery,
)
from app.schemas.dashboard_schema import (
    DashboardStats,
    DiscordAgentStats,
    DiscordSessionSummary,
    WebAgentStats,
)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats", response_model=DashboardStats)
def dashboard_stats(request: Request) -> DashboardStats:
    conversations = request.app.state.auxiliary_store.list_conversations()
    web = WebAgentStats(
        conversation_count=len(conversations),
        message_count=sum(int(item.get("message_count", 0)) for item in conversations),
        last_activity_at=conversations[0]["updated_at"] if conversations else None,
    )

    sessions_factory = request.app.state.postgres_sessions
    with sessions_factory() as database:
        session_count = database.scalar(select(func.count()).select_from(DiscordConversationSession)) or 0
        active_session_count = database.scalar(
            select(func.count()).select_from(DiscordConversationSession).where(DiscordConversationSession.status == "active")
        ) or 0
        turn_counts = {
            str(status): int(count)
            for status, count in database.execute(
                select(DiscordSessionTurn.status, func.count()).group_by(DiscordSessionTurn.status)
            )
        }
        delivery_count = database.scalar(select(func.count()).select_from(DiscordTurnDelivery)) or 0
        last_turn_at = database.scalar(select(func.max(DiscordSessionTurn.updated_at)))
        last_session_at = database.scalar(select(func.max(DiscordConversationSession.last_active_at)))
        last_activity = max(filter(None, [last_turn_at, last_session_at]), default=None)

        turn_count_column = (
            select(func.count())
            .select_from(DiscordSessionTurn)
            .where(DiscordSessionTurn.session_id == DiscordConversationSession.id)
            .correlate(DiscordConversationSession)
            .scalar_subquery()
        )
        recent_rows = database.execute(
            select(DiscordConversationSession, turn_count_column)
            .order_by(DiscordConversationSession.last_active_at.desc())
            .limit(8)
        ).all()
        recent_sessions = [
            DiscordSessionSummary(
                session_id=str(session.id),
                guild_id=session.guild_id,
                channel_id=session.channel_id,
                thread_id=session.thread_id,
                status=session.status,
                turn_count=int(turns or 0),
                last_active_at=session.last_active_at.isoformat() if session.last_active_at else None,
            )
            for session, turns in recent_rows
        ]

    discord = DiscordAgentStats(
        session_count=int(session_count),
        active_session_count=int(active_session_count),
        turn_counts=turn_counts,
        delivery_count=int(delivery_count),
        last_activity_at=last_activity.isoformat() if last_activity else None,
        recent_sessions=recent_sessions,
    )
    return DashboardStats(web=web, discord=discord)
