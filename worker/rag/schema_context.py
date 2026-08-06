# worker/rag/schema_context.py
"""The schema the Text-to-SQL model is shown, and the tables it is allowed to read.

Design doc §7.1 lists schema injection and a read allow-list among the five
safeguards. Both live here because they have to agree: a table described in the
prompt but missing from the guard's list produces a query the model was invited
to write and the guard then rejects, and that failure reads as a guard bug
rather than as the schema drift it actually is.

`claims_flat` is a view, not a table. `claims.data` is `json` rather than `jsonb`
(migrations/versions/917faced2323_initial_schema.py:56), so its values cannot be
grouped or compared without a cast, and one malformed value would break that cast
for every row. The view does the casting once, safely. Creating it is the backend
pair's work - CLAUDE.md §4 keeps migrations there.
"""

from pathlib import Path

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "text_to_sql_v1.txt"

# Read once: the prompt is static and identical for every question.
PROMPT_TEMPLATE = PROMPT_PATH.read_text(encoding="utf-8")

# Not a `{schema}` format field on purpose. The prompt is full of JSON examples,
# so any str.format() over it would fail on the braces - or worse, silently
# mangle an example.
SCHEMA_PLACEHOLDER = "<<SCHEMA>>"

# Everything the model may read.
#
# `claims` itself is absent deliberately: the view carries every useful column
# of it, so leaving the base table out puts the raw `data` json out of reach
# entirely. `raw_messages` carries unmasked source text, `mask_mappings` carries
# the real values behind every placeholder, and `users` carries password hashes.
ALLOWED_TABLES = frozenset({"claims_flat", "audit_trail"})

# The ceiling the prompt states and the guard enforces.
MAX_LIMIT = 100

SCHEMA_TEXT = """\
Tablo: claims_flat  (hasar ihbarları — sorguların çoğu buraya gider)
  id                   bigint
  channel              text     'email' | 'call_transcript' | 'web_form'
  content_type         text     'claim' | 'info_request' | 'irrelevant'
  urgency              text     'critical' | 'high' | 'normal'
  status               text     'in_human_review' | 'approved' | 'archived'
  message_status       text     'received' | 'masked' | 'classified' | 'dead_letter'
  received_at          timestamptz   ihbarın geldiği an — ZAMAN SORULARI BUNU KULLANIR
  created_at           timestamptz   kaydın veritabanına yazıldığı an
  updated_at           timestamptz
  policy_no            text
  plate                text
  incident_date        date
  city                 text
  district             text
  damage_description   text     serbest Türkçe metin
  damage_type          text     'collision' | 'single_vehicle' | 'glass' | 'hail'
                                | 'fire' | 'theft' | 'animal' | 'other'
  injury               boolean  true=yaralanma var, false=yok denmiş, null=belirtilmemiş
  counterparty_exists  boolean  true=karşı taraf var, false=yok denmiş, null=belirtilmemiş
  estimated_amount     numeric  tahmini hasar tutarı, TL

Tablo: audit_trail  (pipeline denetim izi — adım süreleri, hatalar)
  id              bigint
  claim_id        bigint    -> claims_flat.id
  step            text      'masking' | 'masking_sanity' | 'classification' | 'routing'
                            | 'extraction' | 'extraction_error' | 'extraction_skipped'
                            | 'validation' | 'embedding' | 'embedding_error'
                            | 'embedding_skipped' | 'queue_approve' | 'queue_reject'
  provider        text      LLM sağlayıcı, örn. 'openai'
  duration_ms     integer   adımın süresi
  created_at      timestamptz
"""


def build_system_prompt(schema_text: str = SCHEMA_TEXT) -> str:
    """The versioned prompt with the schema injected.

    `schema_text` is a parameter so a test can inject a small schema and assert
    on the result without matching the real one word for word.
    """
    return PROMPT_TEMPLATE.replace(SCHEMA_PLACEHOLDER, schema_text)
