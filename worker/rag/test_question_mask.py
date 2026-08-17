# worker/rag/test_question_mask.py
"""Tests for masking the operator's question. Nothing here touches the network."""

import pytest

from worker.masking.unmask import unmask_text
from worker.rag.question_mask import has_question_placeholder, mask_question


def test_a_plate_in_the_question_is_masked():
    masked, mappings = mask_question("34 ABC 123 plakalı aracın ihbarı ne oldu?")

    assert "34 ABC 123" not in masked
    assert masked == "[Q_PLATE_1] plakalı aracın ihbarı ne oldu?"
    assert [m["real_value"] for m in mappings] == ["34 ABC 123"]


def test_the_mapping_round_trips():
    """What the model writes back has to reveal to what the operator typed."""
    question = "34 ABC 123 plakalı aracın durumu ne?"
    masked, mappings = mask_question(question)

    assert unmask_text(masked, mappings) == question


def test_placeholders_carry_the_question_namespace():
    """Claim text already holds [PLATE_1] from ingest, numbered by a run this
    code cannot see. Sharing the token would let one claim's plate be printed
    for another's."""
    masked, mappings = mask_question("34 ABC 123 plakalı araç")

    assert "[Q_PLATE_1]" in masked
    assert "[PLATE_1]" not in masked.replace("[Q_PLATE_1]", "")
    assert all(m["placeholder"].startswith("[Q_") for m in mappings)


def test_a_question_placeholder_does_not_collide_with_a_claim_placeholder():
    """The point of the namespace, stated as the failure it prevents."""
    masked, mappings = mask_question("34 ABC 123 plakalı araç")
    # What the retrieval path would hand back: the model quoting a snippet whose
    # own plate was masked at ingest, plus the question's placeholder.
    answer = f"{masked} için kaynakta [PLATE_1] görünüyor."

    revealed = unmask_text(answer, mappings)

    assert "34 ABC 123 plakalı araç" in revealed
    assert "[PLATE_1]" in revealed  # the claim's plate is left alone


@pytest.mark.parametrize(
    "question",
    [
        # Measured 2026-08-17: the full pipeline masks "Çağrı" as a name and
        # takes the channel out of the question. The regex layer does not.
        "Çağrı merkezi transkriptinden kaç ihbar geldi?",
        "Çağrı transkriptlerinden kaç tanesi yüksek aciliyetli?",
        "En sık görülen hasar türü hangisi?",
        "Kritik ihbarlarda neler anlatılıyor?",
    ],
)
def test_an_ordinary_question_is_left_alone(question):
    masked, mappings = mask_question(question)

    assert masked == question
    assert mappings == []


def test_has_question_placeholder_ignores_claim_placeholders():
    assert has_question_placeholder("WHERE plate = '[Q_PLATE_1]'")
    assert not has_question_placeholder("kaynakta [PLATE_1] geçiyor")
    assert not has_question_placeholder("hiç yer tutucu yok")
