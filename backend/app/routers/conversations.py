from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.schemas.conversation_schema import ConversationDetail, ConversationRenameRequest, ConversationSummary

from app.security.api_key import require_api_key

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationSummary])
def list_conversations(request: Request) -> list[ConversationSummary]:
    return [ConversationSummary(**conversation) for conversation in request.app.state.auxiliary_store.list_conversations()]


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: str, request: Request) -> ConversationDetail:
    conversation = request.app.state.auxiliary_store.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail={"error_code": "CONVERSATION_NOT_FOUND", "message": f"Conversation {conversation_id} does not exist"})
    return ConversationDetail(**conversation)


@router.patch("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_api_key)])
def rename_conversation(conversation_id: str, payload: ConversationRenameRequest, request: Request) -> None:
    if not request.app.state.auxiliary_store.set_conversation_title(conversation_id, payload.title.strip()):
        raise HTTPException(status_code=404, detail={"error_code": "CONVERSATION_NOT_FOUND", "message": f"Conversation {conversation_id} does not exist"})


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_api_key)])
def delete_conversation(conversation_id: str, request: Request) -> None:
    if not request.app.state.auxiliary_store.delete_conversation(conversation_id):
        raise HTTPException(status_code=404, detail={"error_code": "CONVERSATION_NOT_FOUND", "message": f"Conversation {conversation_id} does not exist"})
