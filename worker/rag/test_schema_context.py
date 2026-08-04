# worker/rag/test_schema_context.py
"""Schema-context tests. No network: the prompt is a file on disk."""

from worker.rag.schema_context import (
    ALLOWED_TABLES,
    MAX_LIMIT,
    SCHEMA_PLACEHOLDER,
    SCHEMA_TEXT,
    build_system_prompt,
)


def test_the_placeholder_is_replaced():
    assert SCHEMA_PLACEHOLDER not in build_system_prompt()


def test_the_schema_reaches_the_prompt():
    prompt = build_system_prompt("Tablo: ornek\n  id  bigint\n")
    assert "Tablo: ornek" in prompt


def test_the_prompt_survives_its_own_json_examples():
    """The reason the placeholder is `<<SCHEMA>>` and not `{schema}`.

    The prompt is full of JSON examples, so a str.format() over it would raise on
    the braces. Injection has to be a plain replace, and the examples have to come
    through intact.
    """
    prompt = build_system_prompt()
    assert '"answerable": true' in prompt
    assert '"refusal_reason": null' in prompt


def test_every_allowed_table_is_described_to_the_model():
    """Drift sentinel.

    A table the guard permits but the schema text never mentions is a table the
    model will not know it can read; the reverse - described but not permitted -
    produces a query the model was invited to write and the guard then refuses.
    """
    for table in ALLOWED_TABLES:
        assert table in SCHEMA_TEXT


def test_the_prompt_states_the_limit_the_guard_enforces():
    assert str(MAX_LIMIT) in build_system_prompt()
