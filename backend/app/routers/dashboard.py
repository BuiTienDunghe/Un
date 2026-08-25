"""Read-only aggregate statistics for the management dashboard.

Web-agent numbers come from the auxiliary store (which already excludes
Discord-origin conversations); Discord-agent numbers are aggregated straight
from the session/turn/delivery tables. Everything here is read-only.
"""
from datetime import datetime, time, timedelta

from fastapi import APIRouter, Request
from sqlalchemy import func, select

from app.postgres.models import (
    DiscordConversationSession,
    DiscordSessionTurn,
    DiscordTurnDelivery,
    RequestLog,
)
from app.schemas.dashboard_schema import (
    DashboardStats,
    DiscordAgentStats,
    DiscordSessionSummary,
    WebAgentStats,
)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


QUESTION_ENDPOINTS = ("/chat", "/rag/chat")


@router.get("/timeseries")
def dashboard_timeseries(request: Request, days: int = 14) -> dict[str, object]:
    """Daily question volume, latency percentiles and error counts (P3-3),
    aggregated from `request_logs` and bucketed in the machine's local
    timezone so "một ngày" matches the operator's day, not UTC's."""
    bounded = max(1, min(int(days), 60))
    local_now = datetime.now().astimezone()
    offset = local_now.utcoffset() or timedelta(0)
    start_date = (local_now - timedelta(days=bounded - 1)).date()
    since = datetime.combine(start_date, time.min, tzinfo=local_now.tzinfo)
    # The database runs in UTC; shifting by the local offset before date()
    # buckets rows by local calendar day.
    local_day = func.date(RequestLog.created_at + offset)

    with request.app.state.postgres_sessions() as database:
        # Status semantics, post D4-lite: "ok" completed; "stopped" the USER
        # aborted the stream (a real question, not a failure); "error" failed.
        # Percentiles take completed turns only — error rows carry a synthetic
        # latency_ms=0 (measured: one such row dragged p50 from 12000 to
        # 10000), and stopped rows carry a duration cut short by the user, so
        # both would describe the corpus of answers with numbers that are not
        # answer latencies.
        question_rows = database.execute(
            select(
                local_day.label("day"),
                func.count(),
                func.percentile_cont(0.5).within_group(RequestLog.latency_ms).filter(RequestLog.status == "ok"),
                func.percentile_cont(0.95).within_group(RequestLog.latency_ms).filter(RequestLog.status == "ok"),
            )
            .where(RequestLog.endpoint.in_(QUESTION_ENDPOINTS), RequestLog.status.in_(["ok", "stopped"]), RequestLog.created_at >= since)
            .group_by(local_day)
        ).all()
        # A user pressing Stop is not an incident; before this filter a single
        # stopped stream painted the chart's first-ever red bar.
        error_rows = database.execute(
            select(local_day.label("day"), func.count())
            .where(RequestLog.status == "error", RequestLog.created_at >= since)
            .group_by(local_day)
        ).all()

    questions = {row[0]: (int(row[1]), row[2], row[3]) for row in question_rows}
    errors = {row[0]: int(row[1]) for row in error_rows}
    series = []
    for index in range(bounded):
        day = start_date + timedelta(days=index)
        count, p50, p95 = questions.get(day, (0, None, None))
        series.append({
            "date": day.isoformat(),
            "questions": count,
            "errors": errors.get(day, 0),
            "p50_ms": int(p50) if p50 is not None else None,
            "p95_ms": int(p95) if p95 is not None else None,
        })
    return {"days": series}


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
