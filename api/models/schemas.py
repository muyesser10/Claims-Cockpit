# api/models/schemas.py
from datetime import datetime
from typing import Any

from pydantic import BaseModel


# Recive request from the user to ingest a message
class IngestRequest(BaseModel):
    channel: str
    raw_text: str
    external_ref: str | None = None
    received_at: datetime | None = None


# Sending response back to the user after ingesting a message
class IngestResponse(BaseModel):
    raw_message_id: int
    status: str


class ClaimOut(BaseModel):
    id: int
    channel: str
    content_type: str | None
    urgency: str | None
    data: dict
    status: str
    created_at: datetime

    # Converts the SQLAlchemy model to a Pydantic model
    class Config:
        from_attributes = True


class ClaimListOut(BaseModel):
    total: int
    items: list[ClaimOut]


# Optional operator edits sent alongside an approve. Keys are extraction
# field names (dotted for nested, e.g. "incident_location.city"); see
# api/routers/queue.py's EDITABLE_FIELDS for the whitelist.
class ApproveRequest(BaseModel):
    edits: dict[str, Any] | None = None


class StatsOut(BaseModel):
    urgency_counts: dict[str, int]
    status_counts: dict[str, int]
    city_counts: dict[str, int]


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
