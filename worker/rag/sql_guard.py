# worker/rag/sql_guard.py
"""Refuses any SQL that is not a single, bounded, read-only SELECT.

Design doc §7.1. This is the second line of defence, not the first. The first is
a read-only database role, which is the backend pair's to configure: a guard that
parses SQL can be wrong about a dialect corner, a role that cannot write cannot
be wrong at all.

Parsed with sqlglot rather than matched with regular expressions. A regex that
checks for a leading SELECT accepts
`WITH x AS (DELETE FROM claims RETURNING *) SELECT * FROM x` - measured here, and
sqlglot reports that statement's root as a Select too, which is why every check
below walks the whole tree rather than looking at the top node. A regex also
cannot tell a semicolon inside a string literal from a statement separator, and
does not see a keyword split by a `/**/` comment.

What comes out is regenerated from the parse tree, not the model's own text: what
runs is what the guard understood. Messages here are English because they go to
the log; the Turkish an operator reads is the answer layer's job.
"""

import sqlglot
from sqlglot import exp

from worker.rag.schema_context import ALLOWED_TABLES, MAX_LIMIT

DIALECT = "postgres"

# Statement types that must not appear anywhere in the tree, including inside a
# CTE. `Command` is the important one: sqlglot wraps anything it cannot parse
# into it, so rejecting Command turns "I did not understand this" into a refusal
# instead of a pass-through.
#
# Held as names, not classes, so test_sql_guard can assert each one still exists.
# sqlglot renames these across versions, and `getattr(exp, name, None)` would let
# an upgrade quietly drop a protection.
FORBIDDEN_NODES = (
    "Insert",
    "Update",
    "Delete",
    "Drop",
    "Create",
    "Alter",
    "TruncateTable",
    "Grant",
    "Copy",
    "Command",
    "Into",
)

# Functions no analytics question needs and an attacker does.
FORBIDDEN_FUNCTIONS = frozenset({"dblink", "lo_import", "lo_export", "query_to_xml"})

# Everything Postgres exposes under this prefix is introspection, file access or
# a sleep. None of it belongs in an answer about claims.
FORBIDDEN_FUNCTION_PREFIX = "pg_"


class SqlGuardError(Exception):
    """The SQL was refused. Not raised for a query that is merely wrong."""


def strip_fences(sql: str) -> str:
    """Drop a markdown fence the model added despite being told not to.

    Rule 1 of the prompt forbids it. Refusing anyway would spend the one
    self-correction round on formatting rather than on the query.
    """
    text = sql.strip()
    if not text.startswith("```"):
        return text

    lines = text.splitlines()[1:]  # opening fence, possibly with a language tag
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def parse_single(sql: str) -> exp.Expression:
    """Parse as PostgreSQL and insist on exactly one statement."""
    try:
        parsed = sqlglot.parse(sql, read=DIALECT)
    except sqlglot.ParseError as exc:
        raise SqlGuardError(f"not parseable as PostgreSQL: {exc}") from exc

    statements = [statement for statement in parsed if statement is not None]
    if len(statements) != 1:
        raise SqlGuardError(f"expected exactly one statement, found {len(statements)}")
    return statements[0]


def check_forbidden_nodes(statement: exp.Expression) -> None:
    """Reject write statements and anything sqlglot could not parse."""
    for name in FORBIDDEN_NODES:
        node_type = getattr(exp, name)
        if next(statement.find_all(node_type), None) is not None:
            raise SqlGuardError(f"{name} is not allowed in a question query")


def check_tables(statement: exp.Expression) -> None:
    """Every table read must be on the allow-list, and unqualified.

    CTE names are excluded: in `WITH recent AS (SELECT ... FROM claims_flat)`,
    sqlglot reports `recent` as a table too, but it is a label for a read that is
    itself checked, not a table of its own. A CTE that shadows an allowed name
    changes nothing - whatever it selects from is still walked.

    A schema qualifier is refused outright rather than checked, because the only
    reason to write one here is to reach `information_schema` or `pg_catalog`.
    """
    cte_names = {cte.alias for cte in statement.find_all(exp.CTE)}

    for table in statement.find_all(exp.Table):
        if table.name in cte_names:
            continue
        if table.db or table.catalog:
            qualified = table.sql(dialect=DIALECT)
            raise SqlGuardError(f"schema-qualified name is not allowed: {qualified}")
        if table.name not in ALLOWED_TABLES:
            raise SqlGuardError(
                f"table '{table.name}' is not readable; allowed: {sorted(ALLOWED_TABLES)}"
            )


def check_functions(statement: exp.Expression) -> None:
    """Reject pg_* and the named escapes.

    Only Anonymous nodes are searched: sqlglot gives the functions an analytics
    query actually uses (COUNT, AVG, DATE_TRUNC) their own types, and everything
    it does not recognise - which is where the dangerous ones live - lands here.
    """
    for function in statement.find_all(exp.Anonymous):
        name = str(function.this).lower()
        if name.startswith(FORBIDDEN_FUNCTION_PREFIX) or name in FORBIDDEN_FUNCTIONS:
            raise SqlGuardError(f"function '{name}' is not allowed")


def apply_limit(statement: exp.Expression) -> exp.Expression:
    """Force a bound: add LIMIT when absent, lower it when too high.

    An existing limit is only left alone when it is an integer literal at or
    below the ceiling - `.limit()` would otherwise *raise* `LIMIT 5` to the
    ceiling. A non-literal limit (`LIMIT 1+1`) is replaced rather than evaluated,
    so the guard never has to work out what a query would have returned.
    """
    limit = statement.args.get("limit")
    if limit is not None:
        value = limit.expression
        if isinstance(value, exp.Literal) and not value.is_string:
            try:
                if int(value.name) <= MAX_LIMIT:
                    return statement
            except ValueError:
                pass

    return statement.limit(MAX_LIMIT)


def check(sql: str) -> str:
    """Validate `sql` and return the bounded, normalized query that may run.

    Raises SqlGuardError with the reason. Order matters: parse first, so every
    later check reads a tree instead of text.
    """
    if not sql or not sql.strip():
        raise SqlGuardError("empty query")

    statement = parse_single(strip_fences(sql))

    if not isinstance(statement, exp.Select):
        # UNION lands here as well, deliberately. No Phase 1 question needs it
        # (an urgency breakdown is a GROUP BY), and accepting it would fork the
        # limit logic. Opening this later is easy; closing it later is not.
        raise SqlGuardError(f"only a single SELECT may run, got {type(statement).__name__}")

    check_forbidden_nodes(statement)
    check_tables(statement)
    check_functions(statement)

    return apply_limit(statement).sql(dialect=DIALECT, comments=False)
