"""Persistent Telegram-native media capture facts."""
from __future__ import annotations

from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.database.schema.models import Base


class TaskMediaCaptureSession(Base):
    """One single-use Bot deep-link media capture session."""

    __tablename__ = "task_media_capture_sessions"

    capture_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    task_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("scheduled_message_tasks.task_id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.account_id", ondelete="CASCADE"), nullable=False
    )
    actor_tg_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expected_task_revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    prompt_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    source_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    saved_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    state: Mapped[str] = mapped_column(String(20), default="waiting", nullable=False)
    error_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    consumed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "state IN ('waiting', 'processing', 'completed', 'expired', 'cancelled', 'failed')",
            name="task_media_capture_state_check",
        ),
        Index("idx_task_media_capture_task_state", "task_id", "state"),
        Index("idx_task_media_capture_actor_prompt", "actor_tg_user_id", "prompt_message_id"),
        Index("idx_task_media_capture_expires", "expires_at"),
    )
