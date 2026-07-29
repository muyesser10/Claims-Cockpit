# worker/extraction/schema.py
"""Extraction output contract — the Pydantic model the LLM must fill in.

Sources:
  - schemas/claim.json           frozen team schema: field names, enum values
  - DS/LLM design doc §3.1-§3.3  safety fields: evidence, confidence, missing

Only extraction-owned fields live here. Deliberately left out:
  - channel       the system knows it at ingest time
  - content_type  classification produces it
  - urgency       classification produces it
"""

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field


class DamageType(StrEnum):
    """Damage categories.

    MUST stay in sync with schemas/claim.json — test_schema.py enforces it.
    """

    COLLISION = "collision"
    SINGLE_VEHICLE = "single_vehicle"
    GLASS = "glass"
    HAIL = "hail"
    FIRE = "fire"
    THEFT = "theft"
    ANIMAL = "animal"
    OTHER = "other"


class IncidentLocation(BaseModel):
    """Where it happened. Either half may be absent from the text."""

    city: str | None = Field(
        default=None,
        description="İl adı. Metinde geçmiyorsa null.",
    )
    district: str | None = Field(
        default=None,
        description="İlçe adı. Metinde geçmiyorsa null.",
    )


class SourceQuote(BaseModel):
    """Evidence for one extracted field: the exact words the model used.

    The model fills in `quote` only. Character offsets are resolved later by
    the pipeline (design doc §3.2) — asking a language model for character
    positions invites invented numbers.
    """

    quote: str = Field(
        description="Ham metinden BİREBİR alıntı. Kelimeleri değiştirme, kısaltma.",
    )


class ClaimExtraction(BaseModel):
    """What the model returns for a single claim message.

    Field order is deliberate: `reasoning` comes first so the model works out
    relative dates and contradictions before it commits to any value.
    """

    # Reasoning first (design doc §3.3). Not persisted to the final record;
    # it stays in the raw log so a wrong answer can be traced back later.
    reasoning: str = Field(
        description=(
            "Önce kısa muhakeme yaz: göreli tarihleri çöz, çelişkileri belirt, "
            "hangi bilgilerin metinde geçmediğini not et. Sonra alanları doldur."
        ),
    )

    # --- Fields from schemas/claim.json ---------------------------------

    policy_no: str | None = Field(
        default=None,
        description="Poliçe numarası, metinde yazdığı gibi. Geçmiyorsa null.",
    )
    plate: str | None = Field(
        default=None,
        description=(
            "Araç plakası. Kanonik format: '34 ABC 123' (boşluklu). "
            "Metinde bitişik yazılmışsa ('34ABC123') boşluklu hale getir. "
            "Geçmiyorsa null."
        ),
    )
    incident_date: date | None = Field(
        default=None,
        description=(
            "Olay tarihi, ISO formatında: YYYY-MM-DD. Göreli ifadeleri "
            "('dün', 'geçen salı') mesajın geliş tarihine göre mutlak tarihe "
            "çevir. Yıl yazmıyorsa mesajın geliş yılını kullan. Geçmiyorsa null."
        ),
    )
    incident_location: IncidentLocation = Field(
        default_factory=IncidentLocation,
        description="Olay yeri. Metinde geçmeyen kısmı null bırak.",
    )
    damage_description: str | None = Field(
        default=None,
        description="Hasarın kısa açıklaması, metne sadık kalarak. Geçmiyorsa null.",
    )
    damage_type: DamageType | None = Field(
        default=None,
        description=(
            "Hasar türü. Yalnızca listedeki değerlerden birini kullan. "
            "Hiçbirine tam oturmuyorsa 'other'. Hasar belli değilse null."
        ),
    )
    injury: bool | None = Field(
        default=None,
        description="Yaralanma var mı? Metin açıkça söylemiyorsa null bırak, false deme.",
    )
    counterparty_exists: bool | None = Field(
        default=None,
        description="Olayda karşı taraf var mı? Metin söylemiyorsa null bırak.",
    )
    estimated_amount: float | None = Field(
        default=None,
        description=(
            "Tahmini hasar tutarı, SAYI olarak (88841). Para birimi, ayraç veya "
            "metin yazma. Türkçe format '1.250,50' → 1250.50. Geçmiyorsa null."
        ),
    )

    # --- Safety fields (design doc §3.2) --------------------------------

    # Principle 1 — no invention. Anything the text does not state stays null
    # and its name is listed here.
    missing_fields: list[str] = Field(
        default_factory=list,
        description=(
            "Metinde geçmediği için null bıraktığın alanların adları. "
            "ASLA tahmin etme veya uydurma — bilmiyorsan null bırak ve buraya yaz."
        ),
    )

    # Principle 2 — evidence. Every value must be traceable to the raw text.
    # The pipeline searches each quote in the source; a quote that is not
    # found marks the field as unreliable.
    source_references: dict[str, SourceQuote] = Field(
        default_factory=dict,
        description=(
            "Doldurduğun HER alan için ham metinden birebir alıntı. "
            "Anahtar alan adı olmalı (ör. 'plate'). Alıntı metinde aynen geçmeli."
        ),
    )

    # Principle 3 — confidence. Self-reported, later combined with
    # deterministic cross-checks in the pipeline.
    field_confidence: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "Doldurduğun her alan için 0.0 ile 1.0 arası güven değeri. Anahtar alan adı olmalı."
        ),
    )
    low_confidence_fields: list[str] = Field(
        default_factory=list,
        description="Doldurdun ama emin olmadığın alanların adları.",
    )
