# worker/classification/schema.py
"""Classification output contract - the Pydantic model the LLM must fill in.

Design doc §4: one cheap call decides content type and urgency together, and an
`info_request` or `irrelevant` verdict stops the pipeline before extraction runs.

Enum values MUST stay in sync with schemas/claim.json; test_schema.py enforces
it, the same way worker/extraction/schema.py does.
"""

from enum import StrEnum

from pydantic import BaseModel, Field


class ContentType(StrEnum):
    """Mesajın türü."""

    # Docstrings in this file are not comments - pydantic ships them to the model
    # as part of the tool schema, so repo-internal notes stay in `#` comments.
    CLAIM = "claim"
    INFO_REQUEST = "info_request"
    IRRELEVANT = "irrelevant"


class Urgency(StrEnum):
    """Triyaj aciliyeti."""

    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"


class ClaimClassification(BaseModel):
    """Bir mesajın içerik tipi ve aciliyeti."""

    # Reasoning first, as in extraction: it makes the model commit to what it saw
    # in the text before it commits to a label.
    reasoning: str = Field(
        description=(
            "Önce kısa muhakeme yaz: içerik tipini neye bakarak seçtin, aciliyeti "
            "hangi ifadeden çıkardın. En fazla 2 cümle."
        ),
    )
    content_type: ContentType = Field(
        description=(
            "Mesajın türü. Olmuş bir olay anlatılıyorsa claim; yalnızca soru "
            "soruluyorsa info_request; sigortayla ilgisi yoksa irrelevant."
        ),
    )
    # The injury pair sits ahead of urgency deliberately. Fields are generated in
    # declaration order, and urgency used to be decided before the model had
    # considered injury at all - while the domain rule runs the other way round:
    # an injury forces critical. Now the evidence is written first, the verdict
    # follows from it, and urgency is answered last, once both are on the page.
    injury_evidence: str | None = Field(
        default=None,
        description=(
            "Yaralanmayı gösteren ifadeyi metinden BİREBİR alıntıla. Kelime ekleme "
            "veya düzeltme yapma. Yaralanma anlatılmıyorsa null bırak."
        ),
    )
    injury_mentioned: bool = Field(
        description=(
            "Yukarıda bir alıntı yazdıysan true, null bıraktıysan false. Alıntısız true verme."
        ),
    )
    urgency: Urgency = Field(
        description=(
            "Aciliyet. Yaralanma varsa critical; yaralanma yok ama araç "
            "kullanılamaz durumdaysa high; aksi halde normal."
        ),
    )
