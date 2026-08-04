# worker/rag/test_sql_guard.py
"""Guard tests. No network and no database - the guard is a pure function over text."""

import pytest
from sqlglot import exp

from worker.rag.schema_context import MAX_LIMIT
from worker.rag.sql_guard import FORBIDDEN_NODES, SqlGuardError, check, strip_fences


def test_forbidden_node_names_still_exist():
    """Version sentinel.

    sqlglot renames expression classes between releases, and the guard looks
    them up by name. If one disappears, `getattr` would raise here rather than a
    protection quietly going missing - which is the whole reason the names are
    not resolved with a default.
    """
    for name in FORBIDDEN_NODES:
        assert hasattr(exp, name), f"sqlglot no longer defines exp.{name}"


# --- what may run -------------------------------------------------------


def test_plain_select_gets_a_limit():
    assert check("SELECT COUNT(*) FROM claims_flat") == (
        f"SELECT COUNT(*) FROM claims_flat LIMIT {MAX_LIMIT}"
    )


def test_a_smaller_limit_is_left_alone():
    """`.limit()` would raise this to the ceiling, which is the opposite of the job."""
    assert check("SELECT * FROM claims_flat LIMIT 5").endswith("LIMIT 5")


def test_an_oversized_limit_is_lowered():
    assert check("SELECT * FROM claims_flat LIMIT 5000").endswith(f"LIMIT {MAX_LIMIT}")


def test_a_non_literal_limit_is_replaced_not_evaluated():
    assert check("SELECT * FROM claims_flat LIMIT 1+1").endswith(f"LIMIT {MAX_LIMIT}")


def test_join_across_both_allowed_tables():
    sql = check(
        "SELECT a.step, AVG(a.duration_ms) FROM audit_trail a "
        "JOIN claims_flat c ON c.id = a.claim_id GROUP BY a.step"
    )
    assert "audit_trail" in sql and "claims_flat" in sql


def test_cte_over_an_allowed_table_is_fine():
    """The CTE name looks like a table to sqlglot; it must not be treated as one."""
    assert check("WITH recent AS (SELECT * FROM claims_flat) SELECT COUNT(*) FROM recent")


def test_comments_are_stripped():
    assert "--" not in check("SELECT COUNT(*) FROM claims_flat -- yorum")


def test_a_semicolon_inside_a_string_is_not_a_statement_separator():
    """The case a regex guard gets wrong."""
    assert check("SELECT * FROM claims_flat WHERE city = ';'")


def test_markdown_fence_is_removed_rather_than_refused():
    sql = check("```sql\nSELECT COUNT(*) FROM claims_flat\n```")
    assert sql.startswith("SELECT COUNT(*)")


def test_strip_fences_leaves_plain_sql_untouched():
    assert strip_fences("  SELECT 1  ") == "SELECT 1"


# --- what may not -------------------------------------------------------


@pytest.mark.parametrize(
    ("sql", "why"),
    [
        ("SELECT 1; DROP TABLE users", "two statements"),
        ("DROP TABLE users", "not a select"),
        ("VACUUM", "sqlglot parses this into Command"),
        ("SELECT 1 UNION SELECT 2", "union is closed in phase 1"),
        ("SELECT * INTO t FROM claims_flat", "select into writes"),
        ("", "empty"),
        ("this is not sql at all !!", "unparseable"),
    ],
)
def test_shape_is_refused(sql, why):
    with pytest.raises(SqlGuardError):
        check(sql)


def test_dml_hidden_in_a_cte_is_refused():
    """The headline case: sqlglot reports this statement's root as a Select.

    A guard that only checked the top node would pass it through.
    """
    with pytest.raises(SqlGuardError, match="Delete"):
        check("WITH x AS (DELETE FROM claims RETURNING *) SELECT * FROM x")


@pytest.mark.parametrize(
    "table",
    ["users", "mask_mappings", "raw_messages", "claims", "claim_embeddings"],
)
def test_tables_outside_the_allow_list_are_refused(table):
    """`claims` included: the view exists so the raw json is out of reach."""
    with pytest.raises(SqlGuardError, match="not readable"):
        check(f"SELECT * FROM {table}")


def test_a_table_in_a_subquery_is_checked_too():
    with pytest.raises(SqlGuardError, match="not readable"):
        check("SELECT * FROM claims_flat WHERE id IN (SELECT id FROM users)")


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM information_schema.tables",
        "SELECT * FROM pg_catalog.pg_tables",
    ],
)
def test_schema_qualified_names_are_refused(sql):
    with pytest.raises(SqlGuardError, match="schema-qualified"):
        check(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT pg_sleep(10)",
        "SELECT pg_read_file('/etc/passwd')",
        "SELECT dblink(a) FROM claims_flat",
    ],
)
def test_dangerous_functions_are_refused(sql):
    with pytest.raises(SqlGuardError, match="not allowed"):
        check(sql)


def test_ordinary_aggregates_are_not_caught_by_the_function_check():
    """The blacklist must not cost us COUNT/AVG/DATE_TRUNC."""
    assert check(
        "SELECT DATE_TRUNC('month', received_at) AS ay, COUNT(*), AVG(estimated_amount) "
        "FROM claims_flat GROUP BY ay"
    )
