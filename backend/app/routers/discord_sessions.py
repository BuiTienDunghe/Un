from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from app.security.api_key import require_api_key

from app.schemas.discord_schema import (
    DiscordSessionResolveRequest,
    DiscordSessionResolveResponse,
    DiscordTurnEnqueueRequest,
    DiscordTurnEnqueueResponse,
    DiscordTurnExecuteResponse,
    DiscordTurnCompleteRequest,
    DiscordTurnFailRequest,
    DiscordTurnOperatorStopResponse,
    DiscordTurnStateResponse,
)
from app.services.discord_session_service import (
    DiscordDirectMessageUnsupportedError,
    DiscordSessionInputError,
)
from app.services.discord_turn_service import (
    DiscordTurnDeliveryConflictError,
    DiscordTurnNotFoundError,
    DiscordTurnOwnershipError,
)


# Every route here enqueues, claims, completes or cancels a Discord turn, so the
# guard belongs on the router rather than repeated on each decorator.
router = APIRouter(prefix="/api/discord/sessions", tags=["discord-sessions"], dependencies=[Depends(require_api_key)])


@router.post("/resolve", response_model=DiscordSessionResolveResponse)
def resolve_discord_session(
    payload: DiscordSessionResolveRequest,
    request: Request,
) -> DiscordSessionResolveResponse:
    try:
        resolution = request.app.state.discord_session_service.resolve(
            payload.guild_id,
            payload.channel_id,
            payload.thread_id,
        )
    except DiscordDirectMessageUnsupportedError as error:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "DISCORD_DM_UNSUPPORTED", "message": str(error)},
        ) from error
    except DiscordSessionInputError as error:
        raise HTTPException(
            status_code=422,
            detail={"error_code": "INVALID_DISCORD_LOCATION", "message": str(error)},
        ) from error
    return DiscordSessionResolveResponse(
        session_id=resolution.session_id,
        backend_conversation_id=resolution.backend_conversation_id,
        created=resolution.created,
        status="active",
    )


@router.post("/{session_id}/turns", response_model=DiscordTurnEnqueueResponse)
def enqueue_discord_turn(
    session_id: UUID,
    payload: DiscordTurnEnqueueRequest,
    request: Request,
) -> DiscordTurnEnqueueResponse:
    try:
        turn = request.app.state.discord_turn_service.enqueue(
            session_id,
            payload.discord_message_id,
            payload.message,
            payload.system_prompt,
            author_id=payload.author_id,
            author_display_name=payload.author_display_name,
            reply_to_discord_message_id=payload.reply_to_discord_message_id,
        )
    except DiscordTurnNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "DISCORD_SESSION_NOT_FOUND", "message": "Discord session does not exist."},
        ) from error
    return DiscordTurnEnqueueResponse(
        turn_id=turn.turn_id,
        session_id=turn.session_id,
        sequence_number=turn.sequence_number,
        status=turn.status,
        created=turn.created,
    )


@router.post("/turns/{turn_id}/execute", response_model=DiscordTurnExecuteResponse)
def execute_discord_turn(turn_id: UUID, request: Request) -> DiscordTurnExecuteResponse:
    try:
        turn = request.app.state.discord_turn_service.execute(turn_id)
    except DiscordTurnNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "DISCORD_TURN_NOT_FOUND", "message": "Discord turn does not exist."},
        ) from error
    except DiscordTurnOwnershipError as error:
        raise HTTPException(
            status_code=409,
            detail={"error_code": "DISCORD_TURN_OWNERSHIP_LOST", "message": str(error)},
        ) from error
    return DiscordTurnExecuteResponse(
        turn_id=turn.turn_id,
        session_id=turn.session_id,
        sequence_number=turn.sequence_number,
        status=turn.status,
        answer=turn.answer,
        model_used=turn.model_used,
        execution_token=turn.execution_token,
        replacement_turn_id=turn.replacement_turn_id,
    )


@router.post("/turns/{turn_id}/complete", response_model=DiscordTurnStateResponse)
def complete_discord_turn(
    turn_id: UUID,
    payload: DiscordTurnCompleteRequest,
    request: Request,
) -> DiscordTurnStateResponse:
    try:
        turn = request.app.state.discord_turn_service.complete(
            turn_id,
            payload.execution_token,
            payload.discord_response_message_ids,
        )
    except DiscordTurnDeliveryConflictError as error:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "DISCORD_TURN_DELIVERY_CONFLICT",
                "message": str(error),
            },
        ) from error
    except DiscordTurnOwnershipError as error:
        raise HTTPException(
            status_code=409,
            detail={"error_code": "DISCORD_TURN_OWNERSHIP_LOST", "message": str(error)},
        ) from error
    return DiscordTurnStateResponse(turn_id=turn.turn_id, status=turn.status)


@router.post("/turns/{turn_id}/fail", response_model=DiscordTurnStateResponse)
def fail_discord_turn(
    turn_id: UUID,
    payload: DiscordTurnFailRequest,
    request: Request,
) -> DiscordTurnStateResponse:
    try:
        turn = request.app.state.discord_turn_service.fail(
            turn_id,
            payload.execution_token,
            payload.error,
            retryable=payload.retryable,
        )
    except DiscordTurnOwnershipError as error:
        raise HTTPException(
            status_code=409,
            detail={"error_code": "DISCORD_TURN_OWNERSHIP_LOST", "message": str(error)},
        ) from error
    return DiscordTurnStateResponse(turn_id=turn.turn_id, status=turn.status)


@router.post(
    "/turns/cancel-open",
    response_model=DiscordTurnOperatorStopResponse,
)
def cancel_open_discord_turns_for_operator_stop(
    request: Request,
) -> DiscordTurnOperatorStopResponse:
    turns = request.app.state.discord_turn_service.cancel_open_for_operator_stop()
    return DiscordTurnOperatorStopResponse(cancelled_turns=len(turns))
