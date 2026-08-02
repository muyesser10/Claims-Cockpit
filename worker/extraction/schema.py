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

from pydantic import BaseModel, Field, field_validator


class DamageType(StrEnum):
    """Hasar türü kategorileri."""

    # Docstrings in this file are not comments — pydantic ships them to the
    # model as part of the tool schema, so repo-internal notes stay in `#`
    # comments. MUST stay in sync with schemas/claim.json; test_schema.py
    # enforces it.
    COLLISION = "collision"
    SINGLE_VEHICLE = "single_vehicle"
    GLASS = "glass"
    HAIL = "hail"
    FIRE = "fire"
    THEFT = "theft"
    ANIMAL = "animal"
    OTHER = "other"


class IncidentLocation(BaseModel):
    """Olayın gerçekleştiği yer."""

    city: str | None = Field(
        default=None,
        description="İl adı. Metinde geçmiyorsa null.",
    )
    district: str | None = Field(
        default=None,
        description="İlçe adı. Metinde geçmiyorsa null.",
    )


# Keys the model reaches for when it decides to wrap a quote in an object
# anyway. Measured 2026-07-30 on gpt-4o: its first answer was a bare string,
# and once the validation error pushed it into an object it invented `text`.
# Both cost a retry, so both are now flattened instead of rejected.
_QUOTE_KEYS = ("quote", "text", "value")


class ClaimExtraction(BaseModel):
    """Tek bir hasar ihbarı mesajından çıkarılan yapılandırılmış veri."""

    # Field order is deliberate: `reasoning` comes first so the model works out
    # relative dates and contradictions before it commits to any value.

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
    # The pipeline searches each quote in the source; a quote that is not found
    # marks the field as unreliable. Offsets are resolved there as well (design
    # doc §3.2), so the model only ever sends the text — a plain string, which
    # is also the shape it produces unprompted.
    source_references: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Doldurduğun HER alan için ham metinden birebir alıntı. "
            'Anahtar alan adı, değer alıntının kendisi olsun: {"plate": "34 ABC 123 plakalı"}. '
            'İç içe alanlarda nokta kullan: "incident_location.city". '
            "Alıntı ham metinde aynen geçmeli — kelimeleri değiştirme, kısaltma."
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

    @field_validator("field_confidence", mode="before")
    @classmethod
    def _drop_null_confidence(cls, value: object) -> object:
        """A field left null has no confidence to report.

        Measured 2026-08-01 over 100 records: the model answers `"injury": null`
        here when it leaves injury null. That is reasonable, and refusing it cost
        two whole calls — three attempts each, all rejected for the same reason.
        The entry carries no information, so it is dropped instead.
        """
        if not isinstance(value, dict):
            return value
        return {key: score for key, score in value.items() if score is not None}

    @field_validator("source_references", mode="before")
    @classmethod
    def _unwrap_quotes(cls, value: object) -> object:
        """Tolerate a wrapped quote instead of paying for a retry.

        A plain string is the contract, but a model that wraps it anyway should
        not cost two extra calls: a nested single-key object was measured at
        three requests per message where one would do. Anything unrecognised is
        passed through untouched so it still fails validation loudly.
        """
        if not isinstance(value, dict):
            return value

        flat = {}
        for field, ref in value.items():
            if isinstance(ref, dict):
                ref = next((ref[key] for key in _QUOTE_KEYS if key in ref), ref)
            flat[field] = ref
        return flat
