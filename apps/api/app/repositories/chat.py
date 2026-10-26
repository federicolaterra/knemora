"""Persistence operations for the product chat boundary."""

from __future__ import annotations

import unicodedata
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.orm import Session

from app.db.models import AgentSession, Conversation, Message, User


class ConversationNotFoundError(LookupError):
    """Raised when a conversation does not exist."""


class ChatRepository:
    """Small unit-of-work repository with explicit commits."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_or_create_user(self, *, email: str, display_name: str) -> User:
        user = self._session.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email, display_name=display_name)
            self._session.add(user)
            self._session.flush()
        return user

    def get_user(self, user_id: uuid.UUID) -> User:
        """Return an active authenticated user."""

        user = self._session.get(User, user_id)
        if user is None or not user.is_active:
            raise ConversationNotFoundError(str(user_id))
        return user

    def create_conversation(self, *, user: User, title: str | None) -> Conversation:
        conversation = Conversation(user_id=user.id, title=title)
        self._session.add(conversation)
        self._session.flush()
        return conversation

    def list_conversations(
        self,
        user_id: uuid.UUID,
        *,
        query: str = "",
        offset: int = 0,
        limit: int = 8,
    ) -> tuple[list[tuple[Conversation, int, datetime]], int]:
        """Return owner-scoped summaries ordered by actual message activity."""

        filters = [Conversation.user_id == user_id]
        normalized_query = query.strip()
        if normalized_query:
            filters.append(Conversation.title.ilike(f"%{normalized_query}%"))
        total = int(self._session.scalar(select(func.count(Conversation.id)).where(*filters)) or 0)
        last_activity = func.coalesce(func.max(Message.created_at), Conversation.created_at)
        rows = self._session.execute(
            select(Conversation, func.count(Message.id), last_activity)
            .outerjoin(Message, Message.conversation_id == Conversation.id)
            .where(*filters)
            .group_by(Conversation.id)
            .order_by(last_activity.desc(), Conversation.id.desc())
            .offset(offset)
            .limit(limit)
        ).all()
        summaries = [(conversation, int(count), activity) for conversation, count, activity in rows]
        return summaries, total

    def get_conversation(self, conversation_id: uuid.UUID, *, user_id: uuid.UUID) -> Conversation:
        conversation = self._session.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
            )
        )
        if conversation is None:
            raise ConversationNotFoundError(str(conversation_id))
        return conversation

    def delete_conversation(self, conversation_id: uuid.UUID, *, user_id: uuid.UUID) -> None:
        """Delete one owner-scoped conversation and its cascading child records."""

        conversation = self.get_conversation(conversation_id, user_id=user_id)
        self._session.delete(conversation)
        self._session.flush()

    def rename_conversation(
        self, conversation_id: uuid.UUID, *, user_id: uuid.UUID, title: str
    ) -> Conversation:
        conversation = self.get_conversation(conversation_id, user_id=user_id)
        conversation.title = title
        self._session.flush()
        return conversation

    def assign_initial_title(self, conversation: Conversation, content: str) -> None:
        """Name the first persisted prompt without replacing a manual title."""

        first_line = next((line.strip() for line in content.splitlines() if line.strip()), "")
        safe_line = "".join(
            " " if unicodedata.category(character).startswith("C") else character
            for character in first_line
        )
        normalized = " ".join(safe_line.split())
        if not normalized:
            return
        has_messages = exists().where(Message.conversation_id == Conversation.id)
        self._session.execute(
            update(Conversation)
            .where(
                Conversation.id == conversation.id,
                or_(
                    Conversation.title.is_(None),
                    Conversation.title.in_(("", "Untitled conversation")),
                ),
                ~has_messages,
            )
            .values(title=normalized[:300])
            .execution_options(synchronize_session=False)
        )
        self._session.flush()
        self._session.refresh(conversation)

    def list_messages(self, conversation_id: uuid.UUID) -> list[Message]:
        return list(
            self._session.scalars(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.sequence)
            )
        )

    def add_message(
        self,
        *,
        conversation_id: uuid.UUID,
        role: str,
        content: str,
        provider_model: str | None = None,
        message_metadata: dict[str, Any] | None = None,
    ) -> Message:
        max_sequence = self._session.scalar(
            select(func.max(Message.sequence)).where(Message.conversation_id == conversation_id)
        )
        message = Message(
            conversation_id=conversation_id,
            sequence=(max_sequence or 0) + 1,
            role=role,
            content=content,
            provider_model=provider_model,
            message_metadata=message_metadata or {},
        )
        self._session.add(message)
        self._session.flush()
        return message

    def ensure_agent_session(
        self, *, conversation_id: uuid.UUID, adk_session_id: str
    ) -> AgentSession:
        agent_session = self._session.scalar(
            select(AgentSession).where(AgentSession.conversation_id == conversation_id)
        )
        if agent_session is None:
            agent_session = AgentSession(
                conversation_id=conversation_id,
                adk_session_id=adk_session_id,
                state={"persistence": "product_database"},
            )
            self._session.add(agent_session)
            self._session.flush()
        else:
            agent_session.adk_session_id = adk_session_id
        return agent_session

    def commit(self) -> None:
        self._session.commit()
