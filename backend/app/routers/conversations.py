from fastapi import APIRouter, HTTPException, Request, status

from app.schemas.conversation_schema import ConversationDetail, ConversationSummary

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


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(conversation_id: str, request: Request) -> None:
    if not request.app.state.auxiliary_store.delete_conversation(conversation_id):
        raise HTTPException(status_code=404, detail={"error_code": "CONVERSATION_NOT_FOUND", "message": f"Conversation {conversation_id} does not exist"})
