#api/models/schemas.py
from pydantic import BaseModel
from datetime import datetime

# Recive request from the user to ingest a message
class IngestRequest(BaseModel):
    channel: str
    raw_text: str

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