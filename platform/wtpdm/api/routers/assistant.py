"""Maintenance assistant: chat (tool-calling LLM over live data), conversation history,
context-aware starter questions, proactive insights since the previous visit, maintenance
recommendations, and answer feedback."""

from __future__ import annotations

import uuid
from datetime import datetime
from functools import lru_cache
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from wtpdm.api import schemas
from wtpdm.api.deps import db
from wtpdm.api.security import Principal, viewer
from wtpdm.assistant import insights, recommendations, suggestions
from wtpdm.assistant.guardrails import MAX_INPUT_CHARS, RateLimiter
from wtpdm.assistant.knowledge import KnowledgeBase
from wtpdm.assistant.llm import LLMError, LLMRateLimited, default_model, suggestion_model
from wtpdm.assistant.service import Assistant, AssistantUnavailable
from wtpdm.db.models import Alert, AppUser, AssistantMessage, Turbine

router = APIRouter(prefix="/assistant", tags=["assistant"])
limiter = RateLimiter(max_requests=12, per_seconds=60)


@lru_cache
def get_assistant() -> Assistant:
    return Assistant(default_model(), KnowledgeBase(), suggestion_model=suggestion_model())


class ChatContext(schemas.Schema):
    page: str | None = Field(default=None, max_length=32)
    turbine_id: str | None = Field(default=None, pattern=r"^[ABC]-\d{1,2}$")
    alert_id: uuid.UUID | None = None


class ChatIn(schemas.Schema):
    message: str = Field(min_length=1, max_length=MAX_INPUT_CHARS * 2)
    conversation_id: uuid.UUID | None = None
    context: ChatContext | None = None


class ToolUse(schemas.Schema):
    name: str
    args: dict[str, Any]
    ok: bool


class Citation(schemas.Schema):
    kind: str
    label: str
    ref: str
    link: str | None


class ChatOut(schemas.Schema):
    conversation_id: uuid.UUID
    message_id: int | None
    answer: str
    blocked: bool
    reason: str | None
    flags: list[str]
    tools: list[ToolUse]
    citations: list[Citation]
    suggestions: list[str]
    suggestion_source: str
    model: str | None
    latency_ms: int


class MessageOut(schemas.ORM):
    id: int
    role: str
    content: str
    citations: list[dict] | None
    flags: list[str] | None
    feedback: int | None
    created_at: datetime


class FeedbackIn(schemas.Schema):
    rating: Literal[-1, 1]
    comment: str | None = Field(default=None, max_length=1000)


@router.get("/status")
def assistant_status(_: Principal = Depends(viewer), assistant: Assistant = Depends(get_assistant)) -> dict:
    return {
        "available": assistant.model is not None,
        "model": assistant.model.name if assistant.model else None,
    }


@router.post("/chat", response_model=ChatOut)
def chat(
    body: ChatIn,
    user: Principal = Depends(viewer),
    s: Session = Depends(db),
    assistant: Assistant = Depends(get_assistant),
):
    """Ask a question. The answer is grounded in tool calls over the live data; figures not
    found in the retrieved data are flagged as unverified."""
    if not limiter.allow(user.username):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many questions; wait a minute")
    ctx = body.context.model_dump(mode="json") if body.context else {}
    if body.context and body.context.turbine_id and s.get(Turbine, body.context.turbine_id) is None:
        ctx.pop("turbine_id")
    try:
        result = assistant.chat(s, user, body.message, body.conversation_id, ctx)
    except AssistantUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except LLMRateLimited as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            str(exc),
            headers={"Retry-After": str(round(exc.retry_after))},
        ) from exc
    except LLMError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"The language model failed: {exc}") from exc
    return ChatOut(
        conversation_id=result.conversation_id,
        message_id=result.message_id,
        answer=result.answer,
        blocked=result.blocked,
        reason=result.reason,
        flags=result.flags,
        tools=[ToolUse(name=c["name"], args=c["args"], ok=c["ok"]) for c in result.tools],
        citations=[Citation(**c) for c in result.citations],
        suggestions=result.suggestions,
        suggestion_source=result.suggestion_source,
        model=result.model,
        latency_ms=result.latency_ms,
    )


@router.get("/conversations/{conversation_id}", response_model=list[MessageOut])
def conversation(conversation_id: uuid.UUID, user: Principal = Depends(viewer), s: Session = Depends(db)):
    """A conversation of the current user (users only see their own)."""
    return s.scalars(
        select(AssistantMessage)
        .where(
            AssistantMessage.conversation_id == conversation_id, AssistantMessage.username == user.username
        )
        .order_by(AssistantMessage.id)
    ).all()


@router.post(
    "/messages/{message_id}/feedback", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
def feedback(
    message_id: int, body: FeedbackIn, user: Principal = Depends(viewer), s: Session = Depends(db)
) -> Response:
    msg = s.get(AssistantMessage, message_id)
    if msg is None or msg.username != user.username or msg.role != "assistant":
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No answer {message_id}")
    msg.feedback, msg.feedback_comment = body.rating, body.comment
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/suggestions")
def starter_questions(
    page: str | None = Query(default=None, max_length=32),
    turbine_id: str | None = Query(default=None, pattern=r"^[ABC]-\d{1,2}$"),
    alert_id: uuid.UUID | None = None,
    _: Principal = Depends(viewer),
    s: Session = Depends(db),
) -> dict:
    return {"suggestions": suggestions.starters(s, turbine_id, str(alert_id) if alert_id else None, page)}


@router.get("/insights")
def proactive_insights(
    since: datetime | None = Query(
        default=None, description="The previous visit; default: the user's last recorded visit"
    ),
    user: Principal = Depends(viewer),
    s: Session = Depends(db),
) -> dict:
    """What changed since the previous visit: new and escalated alerts, resolutions, the
    user's queue, model and retraining changes, drift, turbines below the watch level."""
    if since is None:
        since = s.scalars(select(AppUser.last_seen_at).where(AppUser.username == user.username)).first()
    return insights.since(s, user.username, since)


@router.get("/recommendations")
def maintenance_recommendations(
    alert_id: uuid.UUID | None = None,
    turbine_id: str | None = Query(default=None, pattern=r"^[ABC]-\d{1,2}$"),
    _: Principal = Depends(viewer),
    s: Session = Depends(db),
) -> dict:
    """Advisory maintenance recommendation from the playbook for an alert or a turbine."""
    if alert_id:
        alert = s.get(Alert, alert_id)
        if alert is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No alert {alert_id}")
        return recommendations.for_alert(s, alert)
    if turbine_id:
        if s.get(Turbine, turbine_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No turbine {turbine_id}")
        return recommendations.for_turbine(s, turbine_id)
    raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Give alert_id or turbine_id")
