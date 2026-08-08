#!/bin/bash
# migrations/init/01-create-readonly-role.sh
#
# Creates rag_readonly: the role the Text-to-SQL path runs generated queries as
# (rag/readonly.py). SELECT on claims_flat and audit_trail, nothing else — the
# same list worker/rag/sql_guard.py enforces, but enforced by the database
# instead of only by a parser. A guard that parses SQL can be wrong about a
# dialect corner; a role holding no other privilege cannot be.
#
# Not an Alembic migration on purpose: a role is a cluster object, it needs a
# password, and a password does not belong in a file CI replays.
#
# TWO THINGS TO KNOW BEFORE THIS SURPRISES YOU
#
#   1. The postgres image only runs /docker-entrypoint-initdb.d on an EMPTY data
#      volume. Everyone whose db_data already exists has to run this by hand —
#      the command is in docs/runbook.md.
#   2. It runs BEFORE `alembic upgrade head`, so on a fresh volume claims_flat
#      and audit_trail do not exist yet. The role is still created; the table
#      grants are applied to whatever is already there and warned about
#      otherwise. Re-running the script after the migrations finishes the job.
#      Every statement here is idempotent, so re-running is always safe.

set -euo pipefail

if [ -z "${RAG_READONLY_DB_PASSWORD:-}" ]; then
    echo "rag_readonly: RAG_READONLY_DB_PASSWORD is not set, skipping role creation." >&2
    echo "rag_readonly: the rag service will fall back to DATABASE_URL (NO read isolation)." >&2
    exit 0
fi

# The password goes in as a psql variable, so :'rag_password' below is quoted
# and escaped as a literal by psql. Pasting $RAG_READONLY_DB_PASSWORD into the
# SQL text instead would break on a quote character and would put the password
# into the server log.
psql -v ON_ERROR_STOP=1 \
     --username "$POSTGRES_USER" \
     --dbname "$POSTGRES_DB" \
     -v rag_password="$RAG_READONLY_DB_PASSWORD" \
     -v db_name="$POSTGRES_DB" <<'EOSQL'
-- CREATE ROLE has no IF NOT EXISTS.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rag_readonly') THEN
        CREATE ROLE rag_readonly LOGIN;
    END IF;
END
$$;

-- Outside the DO block deliberately: psql does not substitute its variables
-- inside a dollar-quoted string, so :'rag_password' would be sent verbatim.
ALTER ROLE rag_readonly WITH LOGIN PASSWORD :'rag_password';

GRANT CONNECT ON DATABASE :"db_name" TO rag_readonly;
GRANT USAGE ON SCHEMA public TO rag_readonly;

-- Everything else stays unreachable by omission - no GRANT, no access. That
-- includes `claims`, whose data column holds the unmasked extraction, and it is
-- why the SQL path gets its own connection rather than sharing the api's.
DO $$
DECLARE
    target text;
BEGIN
    FOREACH target IN ARRAY ARRAY['claims_flat', 'audit_trail'] LOOP
        IF to_regclass('public.' || target) IS NULL THEN
            RAISE WARNING
                '% does not exist yet - re-run this script after "alembic upgrade head"',
                target;
        ELSE
            EXECUTE format('GRANT SELECT ON public.%I TO rag_readonly', target);
            RAISE NOTICE 'granted SELECT on % to rag_readonly', target;
        END IF;
    END LOOP;
END
$$;
EOSQL

echo "rag_readonly: role configured."
