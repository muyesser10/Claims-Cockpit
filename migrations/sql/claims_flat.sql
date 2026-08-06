-- claims_flat: the read surface /soru's Text-to-SQL path is allowed to query.
--
-- Owned by the backend pair (CLAUDE.md §4 keeps migrations there); this file is
-- the definition only, to be wrapped in an `op.execute()` inside their revision.
-- It lives in the repo so the definition and the prompt that describes it can be
-- reviewed together: the column list here must match SCHEMA_TEXT in
-- worker/rag/schema_context.py word for word, or the model writes queries against
-- columns that do not exist.
--
-- claims.data is `json`, not `jsonb` (917faced2323_initial_schema.py:56), so its
-- values cannot be grouped or compared without a cast. Casting inline in every
-- generated query would break on one malformed value; the view casts once, and
-- pg_input_is_valid turns "unparseable" into NULL rather than an error that takes
-- the whole result set down with it.
--
-- pg_input_is_valid needs PostgreSQL 16. The compose image is pgvector/pgvector:pg16.
--
-- Note for whoever runs this: the view is not indexable, so queries seq-scan
-- claims. Fine at demo size; revisit as a materialized view if the corpus grows.

CREATE OR REPLACE VIEW claims_flat AS
SELECT
    c.id,
    c.channel,
    c.content_type,
    c.urgency,
    c.status,
    r.status                                  AS message_status,
    r.received_at,
    c.created_at,
    c.updated_at,
    x.e ->> 'policy_no'                       AS policy_no,
    x.e ->> 'plate'                           AS plate,
    CASE WHEN pg_input_is_valid(x.e ->> 'incident_date', 'date')
         THEN (x.e ->> 'incident_date')::date
    END                                       AS incident_date,
    x.e -> 'incident_location' ->> 'city'     AS city,
    x.e -> 'incident_location' ->> 'district' AS district,
    x.e ->> 'damage_description'              AS damage_description,
    x.e ->> 'damage_type'                     AS damage_type,
    CASE WHEN pg_input_is_valid(x.e ->> 'injury', 'boolean')
         THEN (x.e ->> 'injury')::boolean
    END                                       AS injury,
    CASE WHEN pg_input_is_valid(x.e ->> 'counterparty_exists', 'boolean')
         THEN (x.e ->> 'counterparty_exists')::boolean
    END                                       AS counterparty_exists,
    CASE WHEN pg_input_is_valid(x.e ->> 'estimated_amount', 'numeric')
         THEN (x.e ->> 'estimated_amount')::numeric
    END                                       AS estimated_amount
FROM claims c
JOIN raw_messages r ON r.id = c.raw_message_id
CROSS JOIN LATERAL (SELECT c.data -> 'extraction') AS x(e);
