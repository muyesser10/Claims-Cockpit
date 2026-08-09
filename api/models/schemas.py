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


class TrendPoint(BaseModel):
    date: str
    count: int


class StatsOut(BaseModel):
    urgency_counts: dict[str, int]
    status_counts: dict[str, int]
    city_counts: dict[str, int]
    trend: list[TrendPoint]
    last_claim_at: datetime | None


# --- Kalite metrikleri (Metrikler ekranı) ---------------------------------
# Şekil eval/report.py'nin ürettiği quality_report.json ile birebir. Oradaki
# dataclass'lar tek doğruluk kaynağı; buradakiler onun API karşılığı.


class QualitySample(BaseModel):
    """Metriğin neyin üzerinden ölçüldüğü. Ölçülmemiş metrikte `n` null."""

    n: int | None
    unit: str
    description: str


class QualitySource(BaseModel):
    """Sayının nereden geldiği — ekranda künye olarak gösterilir."""

    run: str
    measured_at: str | None
    model: str | None = None


class QualityBreakdown(BaseModel):
    """Manşet sayının bir bileşeni (kanal, sınıf ya da maskeleme katmanı)."""

    label: str
    value: float | None
    numerator: int | None = None
    denominator: int | None = None


class QualityMetric(BaseModel):
    """§7 tablosunun bir satırı."""

    key: str
    label: str
    value: float | None
    unit: str  # "ratio" | "seconds"
    target: float
    target_operator: str  # "gte" | "lte"
    status: str  # "pass" | "fail" | "unmeasured"
    sample: QualitySample
    source: QualitySource | None = None
    numerator: int | None = None
    denominator: int | None = None
    breakdown: list[QualityBreakdown] = []
    notes: list[str] = []


class QualitySummary(BaseModel):
    """Kaç metrik tuttu, kaçı tutmadı, kaçı hiç ölçülmedi."""

    total: int
    passed: int
    failed: int
    unmeasured: int


class QualityReportOut(BaseModel):
    schema_version: int
    generated_at: str
    summary: QualitySummary
    metrics: list[QualityMetric]


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
