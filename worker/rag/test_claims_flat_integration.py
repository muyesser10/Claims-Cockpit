# worker/rag/test_claims_flat_integration.py
"""claims_flat against a real Postgres.

Skipped unless RAG_INTEGRATION_DB is set, the same arrangement as
test_retrieval_integration.py. SQLite cannot stand in for this one: the view is
built from `#>>`, a json column and two plpgsql functions, none of which exist
there - the statement is a syntax error, not a wrong answer.

The view is a migration artifact (298f7de96ab6) and `Base.metadata.create_all`
does not create views, so the target database has to be migrated first:

    docker compose start db
    $env:DATABASE_URL = "postgresql://claims:...@localhost:5433/claims_cockpit"
    alembic upgrade head
    $env:RAG_INTEGRATION_DB = "postgresql+psycopg://claims:...@localhost:5433/claims_cockpit"
    pytest worker/rag/test_claims_flat_integration.py -q

What is tested is the view's SQL - the join, the flattening of
`claims.data['extraction']`, and the two guarded casts. Nothing here goes
through the LLM or the guard; those have their own tests.
"""

import os
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from api.models.db import Base, Claim, RawMessage

pytestmark = pytest.mark.skipif(
    not os.environ.get("RAG_INTEGRATION_DB"),
    reason="needs Postgres with the migrations applied; set RAG_INTEGRATION_DB",
)

# What extraction writes when everything is present, in the shape
# worker/pipeline.py:195 stores it (Pydantic model_dump(mode="json")).
FULL_EXTRACTION = {
    "policy_no": "POL-2026-00001",
    "plate": "34 ABC 123",
    "incident_date": "2026-07-15",
    "incident_location": {"city": "Istanbul", "district": "Kadikoy"},
    "damage_description": "On tampon cizildi",
    "damage_type": "collision",
    "injury": True,
    "counterparty_exists": False,
    "estimated_amount": 12500.5,
}

_TRUNCATE = "TRUNCATE claim_embeddings, audit_trail, claims, raw_messages CASCADE"


@pytest.fixture
def db():
    engine = create_engine(os.environ["RAG_INTEGRATION_DB"])
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()

    # create_all builds the tables but never the view, so a database that has
    # not been migrated fails every test below for one reason. Say it once.
    if not session.execute(text("SELECT to_regclass('public.claims_flat') IS NOT NULL")).scalar():
        session.close()
        pytest.skip("claims_flat is missing - run `alembic upgrade head` on this database")

    session.execute(text(_TRUNCATE))
    session.commit()
    try:
        yield session
    finally:
        session.execute(text(_TRUNCATE))
        session.commit()
        session.close()


def _add_claim(
    db_session,
    *,
    extraction: dict | None = None,
    masked_text: str = "Arac hasar gordu.",
    urgency: str = "normal",
    status: str = "in_human_review",
    message_status: str = "classified",
    received_at: datetime | None = None,
) -> Claim:
    """One claim and the raw message it came from, committed."""
    message = RawMessage(
        channel="email",
        raw_text="ham metin",
        status=message_status,
        received_at=received_at or datetime(2026, 8, 1, 10, 0, tzinfo=UTC),
    )
    db_session.add(message)
    db_session.flush()

    data: dict = {"masked_text": masked_text}
    if extraction is not None:
        data["extraction"] = extraction

    claim = Claim(
        raw_message_id=message.id,
        channel="email",
        content_type="claim",
        urgency=urgency,
        data=data,
        status=status,
    )
    db_session.add(claim)
    db_session.commit()
    return claim


def _row(db_session, claim_id: int):
    """The claims_flat row for a claim, as a mapping."""
    result = db_session.execute(text("SELECT * FROM claims_flat WHERE id = :id"), {"id": claim_id})
    return result.mappings().one()


# --- the ordinary case --------------------------------------------------


def test_a_complete_extraction_maps_to_every_column(db):
    claim = _add_claim(db, extraction=FULL_EXTRACTION)

    row = _row(db, claim.id)

    assert row["policy_no"] == "POL-2026-00001"
    assert row["plate"] == "34 ABC 123"
    assert row["incident_date"] == date(2026, 7, 15)
    assert row["damage_description"] == "On tampon cizildi"
    assert row["damage_type"] == "collision"
    assert row["injury"] is True
    assert row["counterparty_exists"] is False
    assert row["estimated_amount"] == Decimal("12500.5")


def test_incident_location_is_flattened_into_city_and_district(db):
    """The one field the prompt describes flat and claim.json nests."""
    claim = _add_claim(db, extraction=FULL_EXTRACTION)

    row = _row(db, claim.id)

    assert row["city"] == "Istanbul"
    assert row["district"] == "Kadikoy"


def test_a_half_filled_location_leaves_the_missing_half_null(db):
    claim = _add_claim(db, extraction={"incident_location": {"city": "Ankara"}})

    row = _row(db, claim.id)

    assert row["city"] == "Ankara"
    assert row["district"] is None


def test_message_status_and_received_at_come_from_the_raw_message(db):
    """Neither column exists on claims; both arrive through the join."""
    claim = _add_claim(
        db,
        extraction=FULL_EXTRACTION,
        status="approved",
        message_status="classified",
        received_at=datetime(2026, 7, 30, 8, 30, tzinfo=UTC),
    )

    row = _row(db, claim.id)

    assert row["status"] == "approved"
    assert row["message_status"] == "classified"
    assert row["received_at"] == datetime(2026, 7, 30, 8, 30, tzinfo=UTC)


def test_a_claim_without_extraction_still_appears(db):
    """Extraction can be skipped or fail; the claim must not vanish from the view.

    Its urgency is the whole point of the queue, so dropping the row here would
    hide exactly the claims that need attention.
    """
    claim = _add_claim(db, extraction=None, urgency="critical")

    row = _row(db, claim.id)

    assert row["urgency"] == "critical"
    assert row["policy_no"] is None
    assert row["incident_date"] is None
    assert row["estimated_amount"] is None


# --- the guarded casts --------------------------------------------------


def test_a_malformed_amount_is_null_and_does_not_break_the_query(db):
    """The reason safe_cast_numeric exists.

    A bare `::numeric` would abort the whole statement, so this aggregate -
    which never mentions the broken row - would fail too. `api/routers/queue.py`
    writes operator edits without validating their type, so the value is
    reachable through the approve endpoint.
    """
    clean = _add_claim(db, extraction={**FULL_EXTRACTION, "estimated_amount": 12500.5})
    broken = _add_claim(db, extraction={**FULL_EXTRACTION, "estimated_amount": "1.250,50 TL"})

    aggregate = (
        db.execute(
            text(
                "SELECT AVG(estimated_amount) AS ortalama, COUNT(*) AS adet "
                "FROM claims_flat WHERE injury = true"
            )
        )
        .mappings()
        .one()
    )

    # Both rows are counted; only the castable one reaches the average.
    assert aggregate["adet"] == 2
    assert aggregate["ortalama"] == Decimal("12500.5")
    assert _row(db, broken.id)["estimated_amount"] is None
    assert _row(db, clean.id)["estimated_amount"] == Decimal("12500.5")


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        (12500.5, Decimal("12500.5")),
        ("12500.5", Decimal("12500.5")),  # a number the model sent as a string
        (1e25, Decimal("1e+25")),  # json.dumps writes this in exponent form
        ("1.250,50 TL", None),
        ("abc", None),
        ("", None),
    ],
)
def test_amount_casts_or_becomes_null(db, stored, expected):
    claim = _add_claim(db, extraction={"estimated_amount": stored})

    assert _row(db, claim.id)["estimated_amount"] == expected


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        ("2026-07-15", date(2026, 7, 15)),
        ("2026-02-31", None),  # well-formed but not a real day - regex misses this
        ("2026-13-01", None),
        ("15/07/2026", None),
        ("yarin", None),
        ("", None),
    ],
)
def test_date_casts_or_becomes_null(db, stored, expected):
    claim = _add_claim(db, extraction={"incident_date": stored})

    assert _row(db, claim.id)["incident_date"] == expected


def test_a_malformed_date_does_not_break_a_query_that_filters_on_it(db):
    good = _add_claim(db, extraction={"incident_date": "2026-07-15"})
    _add_claim(db, extraction={"incident_date": "2026-02-31"})

    rows = (
        db.execute(text("SELECT id FROM claims_flat WHERE incident_date >= DATE '2026-01-01'"))
        .scalars()
        .all()
    )

    assert rows == [good.id]


# --- the three-way booleans ---------------------------------------------


@pytest.mark.parametrize(
    ("extraction", "expected"),
    [
        ({"counterparty_exists": True}, True),
        ({"counterparty_exists": False}, False),
        ({}, None),  # the field was never mentioned in the message
        ({"counterparty_exists": None}, None),  # extraction left it null explicitly
        ({"counterparty_exists": "belki"}, None),  # unrecognised - not a yes
    ],
)
def test_counterparty_exists_keeps_the_three_way_distinction(db, extraction, expected):
    """Prompt rule 6: null means "not mentioned", not "no"."""
    claim = _add_claim(db, extraction=extraction)

    assert _row(db, claim.id)["counterparty_exists"] is expected


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        (True, True),
        (False, False),
        ("True", True),  # an operator edit past the missing type validation
        ("FALSE", False),
        ("evet", None),
    ],
)
def test_injury_reads_case_insensitively(db, stored, expected):
    claim = _add_claim(db, extraction={"injury": stored})

    assert _row(db, claim.id)["injury"] is expected
