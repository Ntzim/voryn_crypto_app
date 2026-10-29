import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from app.core.config import get_settings
from app.modules.ai import service
from app.modules.ai.llm.base import LLMProvider
from app.modules.auth.deps import CurrentAuth, DbSession

router = APIRouter(prefix="/ai", tags=["ai"])


def get_llm_provider() -> LLMProvider | None:
    return service.provider_or_none()


def require_provider(
    provider: Annotated[LLMProvider | None, Depends(get_llm_provider)],
) -> LLMProvider:
    if provider is None:
        raise service.AIUnavailableError()
    return provider


Provider = Annotated[LLMProvider, Depends(require_provider)]


class StatusOut(BaseModel):
    enabled: bool
    model: str | None
    messages_per_hour: int
    max_turns_per_conversation: int
    usage_today: dict[str, int]


class ConversationOut(BaseModel):
    id: uuid.UUID
    title: str
    model: str
    turns: int
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    id: int
    role: str
    text: str
    sources: list[str]
    tool_calls: list[dict[str, Any]]
    created_at: datetime


class ConversationDetailOut(ConversationOut):
    messages: list[MessageOut]
    can_continue: bool


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=4000)

    @field_validator("content")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Escreva uma pergunta.")
        return value


@router.get("/status")
async def ai_status(
    auth: CurrentAuth,
    db: DbSession,
    provider: Annotated[LLMProvider | None, Depends(get_llm_provider)],
) -> StatusOut:
    settings = get_settings()
    return StatusOut(
        enabled=provider is not None,
        model=provider.model if provider else None,
        messages_per_hour=settings.ai_messages_per_hour,
        max_turns_per_conversation=settings.ai_max_turns_per_conversation,
        usage_today=await service.usage_today(db, auth.user.id),
    )


def _conv_out(c: Any) -> ConversationOut:
    return ConversationOut(
        id=c.id,
        title=c.title,
        model=c.model,
        turns=c.turns,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


@router.get("/conversations")
async def list_conversations(auth: CurrentAuth, db: DbSession) -> list[ConversationOut]:
    return [_conv_out(c) for c in await service.list_conversations(db, auth.user.id)]


@router.post("/conversations", status_code=status.HTTP_201_CREATED)
async def create_conversation(
    auth: CurrentAuth, db: DbSession, provider: Provider
) -> ConversationOut:
    return _conv_out(await service.create_conversation(db, auth.user.id, provider))


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: uuid.UUID, auth: CurrentAuth, db: DbSession
) -> ConversationDetailOut:
    conv = await service.get_owned(db, auth.user.id, conversation_id)
    messages = await service.visible_messages(db, conv)
    return ConversationDetailOut(
        **_conv_out(conv).model_dump(),
        can_continue=conv.turns < get_settings().ai_max_turns_per_conversation,
        messages=[
            MessageOut(
                id=m.id,
                role="user" if m.role == "user" else "assistant",
                text=m.display_text or "",
                sources=m.sources,
                tool_calls=[{"name": t["name"], "ok": t["ok"]} for t in m.tool_calls],
                created_at=m.created_at,
            )
            for m in messages
        ],
    )


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(conversation_id: uuid.UUID, auth: CurrentAuth, db: DbSession) -> None:
    await service.delete_conversation(
        db, await service.get_owned(db, auth.user.id, conversation_id)
    )


@router.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: uuid.UUID,
    data: MessageIn,
    auth: CurrentAuth,
    db: DbSession,
    provider: Provider,
) -> StreamingResponse:
    """Stream the reply as Server-Sent Events: start, status, delta, notice, error, done."""
    conv = await service.get_owned(db, auth.user.id, conversation_id)
    await service.check_can_send(db, auth.user, conv, provider)
    return StreamingResponse(
        service.stream_reply(
            user_id=auth.user.id,
            conversation_id=conv.id,
            text=data.content,
            provider=provider,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
