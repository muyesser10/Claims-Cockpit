"""add claims_flat view

Revision ID: 298f7de96ab6
Revises: 159a1c861269
Create Date: 2026-08-06 19:44:38.498723

`claims_flat` is what the Text-to-SQL path reads (worker/rag/schema_context.py).
It exists because `claims.data` is `json` rather than `jsonb`: its values cannot
be grouped or compared without a cast, and the view does that casting once.

The two risky casts go through safe_cast_date/safe_cast_numeric rather than
`::date` and `::numeric` directly. A cast error in Postgres aborts the whole
statement, so one malformed value would take down every query against the view -
including queries that never mention the broken column. That value is reachable
rather than hypothetical: `api/routers/queue.py` writes operator edits into
`claims.data` without validating their type (ApproveRequest.edits is typed
`dict[str, Any]`), and incident_date and estimated_amount are both editable.

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "298f7de96ab6"
down_revision: str | Sequence[str] | None = "159a1c861269"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# text -> date, NULL instead of an error.
#
# IMMUTABLE is only honest here because of the SET: a bare text->date cast reads
# the DateStyle GUC, which would make the result depend on the session. Pinning
# the style removes that input, and ISO/YMD is what the pipeline writes anyway
# (Pydantic `date`, serialized by model_dump(mode="json")).
SAFE_CAST_DATE = """
CREATE FUNCTION safe_cast_date(value text) RETURNS date
    LANGUAGE plpgsql
    IMMUTABLE
    STRICT
    PARALLEL SAFE
    SET DateStyle = 'ISO, YMD'
AS $$
BEGIN
    RETURN value::date;
EXCEPTION
    WHEN others THEN
        RETURN NULL;
END;
$$
"""

# text -> numeric, NULL instead of an error. No SET clause needed: numeric input
# reads no GUC, so IMMUTABLE holds on its own.
SAFE_CAST_NUMERIC = """
CREATE FUNCTION safe_cast_numeric(value text) RETURNS numeric
    LANGUAGE plpgsql
    IMMUTABLE
    STRICT
    PARALLEL SAFE
AS $$
BEGIN
    RETURN value::numeric;
EXCEPTION
    WHEN others THEN
        RETURN NULL;
END;
$$
"""

# The 19 columns of worker/rag/schema_context.py:42-61, in that order.
#
# `message_status` and `received_at` come from raw_messages - claims carries
# neither, and received_at is the column every time-question is answered from
# (prompt rule 4). The join is INNER because claims.raw_message_id is NOT NULL
# behind a foreign key, so it cannot drop a claim.
#
# The three-way CASE on the booleans is the contract rather than defensiveness:
# prompt rule 6 separates false ("said there was none") from NULL ("not
# mentioned"), so anything unrecognised has to land on NULL. lower() is there
# because an operator edit can write "True" past the missing type validation,
# and reading that as "not mentioned" would be the wrong answer, not a safe one.
CREATE_CLAIMS_FLAT = """
CREATE VIEW claims_flat AS
SELECT
    c.id,
    c.channel,
    c.content_type,
    c.urgency,
    c.status,
    r.status                                              AS message_status,
    r.received_at,
    c.created_at,
    c.updated_at,
    c.data #>> '{extraction,policy_no}'                   AS policy_no,
    c.data #>> '{extraction,plate}'                       AS plate,
    safe_cast_date(
        c.data #>> '{extraction,incident_date}'
    )                                                     AS incident_date,
    c.data #>> '{extraction,incident_location,city}'      AS city,
    c.data #>> '{extraction,incident_location,district}'  AS district,
    c.data #>> '{extraction,damage_description}'          AS damage_description,
    c.data #>> '{extraction,damage_type}'                 AS damage_type,
    CASE lower(c.data #>> '{extraction,injury}')
        WHEN 'true' THEN true
        WHEN 'false' THEN false
        ELSE NULL
    END                                                   AS injury,
    CASE lower(c.data #>> '{extraction,counterparty_exists}')
        WHEN 'true' THEN true
        WHEN 'false' THEN false
        ELSE NULL
    END                                                   AS counterparty_exists,
    safe_cast_numeric(
        c.data #>> '{extraction,estimated_amount}'
    )                                                     AS estimated_amount
FROM claims c
JOIN raw_messages r ON r.id = c.raw_message_id
"""


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(SAFE_CAST_DATE)
    op.execute(SAFE_CAST_NUMERIC)
    op.execute(CREATE_CLAIMS_FLAT)


def downgrade() -> None:
    """Downgrade schema."""
    # The view depends on both functions, so it has to go first - Postgres
    # refuses to drop a function a view still calls.
    op.execute("DROP VIEW IF EXISTS claims_flat")
    op.execute("DROP FUNCTION IF EXISTS safe_cast_numeric(text)")
    op.execute("DROP FUNCTION IF EXISTS safe_cast_date(text)")
