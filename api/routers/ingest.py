# api/routers/ingest.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.database import get_db
from api.models.db import RawMessage
from api.models.schemas import IngestRequest, IngestResponse
from api.redis_client import enqueue_message

router = APIRouter(prefix="/ingest", tags=["ingest"])

# NOT (S3-8): kasıtlı olarak JWT korumasız bırakıldı. Bu uç, e-posta/çağrı
# merkezi/web form entegrasyonlarından gelen servis-to-servis trafiği alıyor
# — kullanıcı oturumu yok, bu yüzden operatör JWT'si burada uygun bir model
# değil. İleride bir API key / servis kimlik doğrulaması eklenecek; S3-8
# kapsamı dışında.


@router.post("", response_model=IngestResponse, status_code=202)
def ingest(payload: IngestRequest, db: Session = Depends(get_db)):
    """Accept a new raw message, store it, enqueue for the worker."""
    msg = RawMessage(
        channel=payload.channel,
        raw_text=payload.raw_text,
        external_ref=payload.external_ref,
    )
    if payload.received_at is not None:
        msg.received_at = payload.received_at

    db.add(msg)
    db.commit()
    db.refresh(msg)

    enqueue_message(msg.id)

    return IngestResponse(raw_message_id=msg.id, status="queued")
