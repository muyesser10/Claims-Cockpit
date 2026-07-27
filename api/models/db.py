# api/models/db.py
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


# Base class for all models
class Base(DeclarativeBase):
    pass


class RawMessage(Base):
    __tablename__ = "raw_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    channel: Mapped[str] = mapped_column(String(32))
    raw_text: Mapped[str] = mapped_column(Text)
    external_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    status: Mapped[str] = mapped_column(String(32), default="received")


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    raw_message_id: Mapped[int] = mapped_column(ForeignKey("raw_messages.id"))
    channel: Mapped[str] = mapped_column(String(32))
    content_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    urgency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="received")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# Decision explanation model
class AuditTrail(Base):
    __tablename__ = "audit_trail"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    claim_id: Mapped[int | None] = mapped_column(ForeignKey("claims.id"), nullable=True)
    raw_message_id: Mapped[int | None] = mapped_column(ForeignKey("raw_messages.id"), nullable=True)
    step: Mapped[str] = mapped_column(String(32))
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MaskMapping(Base):
    __tablename__ = "mask_mappings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    raw_message_id: Mapped[int] = mapped_column(ForeignKey("raw_messages.id"))
    placeholder: Mapped[str] = mapped_column(String(32))
    real_value: Mapped[str] = mapped_column(Text)
    pii_type: Mapped[str] = mapped_column(String(32))


class ClaimEmbedding(Base):
    __tablename__ = "claim_embeddings"

    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id"), primary_key=True)
    embedding = mapped_column(Vector(384))


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16))
