# worker/rag/test_retrieval.py
"""Tests for the snippet half of retrieval.

search() needs pgvector's operators, which SQLite does not have, so it lives in
test_retrieval_integration.py against a real Postgres. Everything here is pure:
a stub encoder, no database, no model.
"""

from worker.embedding.encoder import EMBEDDING_DIMENSIONS
from worker.rag.retrieval import pick_snippets

# A dot product against this returns a vector's first component, which is how
# these tests state "this sentence is the closest" without writing 384 floats.
QUESTION_VECTOR = [1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1)


class RecordingEncoder:
    """Scores sentences from a lookup table and records how it was called.

    Which method ran matters as much as the result: e5's query and passage
    markers are not interchangeable, and using the wrong one degrades retrieval
    without failing anything (ADR-002).
    """

    def __init__(self, scores: dict[str, float] | None = None) -> None:
        self.scores = scores or {}
        self.passage_calls: list[list[str]] = []
        self.query_calls: list[str] = []

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        self.passage_calls.append(list(texts))
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        self.query_calls.append(text)
        return self._vector(text)

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * EMBEDDING_DIMENSIONS
        vector[0] = self.scores.get(text.strip(), 0.0)
        return vector


def test_picks_the_sentence_closest_to_the_question():
    text = "Arac park halindeydi. Dolu yagdi ve cam kirildi. Sigortayi aradim."
    encoder = RecordingEncoder(
        {
            "Arac park halindeydi.": 0.2,
            "Dolu yagdi ve cam kirildi.": 0.9,
            "Sigortayi aradim.": 0.1,
        }
    )

    assert pick_snippets(QUESTION_VECTOR, [text], encoder) == ["Dolu yagdi ve cam kirildi."]


def test_every_sentence_is_embedded_in_one_batch():
    """A call per claim would pay the encoder's fixed cost once per hit."""
    texts = ["Bir cumle. Iki cumle.", "Uc cumle. Dort cumle.", "Bes cumle. Alti cumle."]
    encoder = RecordingEncoder()

    pick_snippets(QUESTION_VECTOR, texts, encoder)

    assert len(encoder.passage_calls) == 1
    assert len(encoder.passage_calls[0]) == 6


def test_sentences_go_in_as_passages_not_queries():
    encoder = RecordingEncoder()

    pick_snippets(QUESTION_VECTOR, ["Tek bir cumle."], encoder)

    assert encoder.passage_calls == [["Tek bir cumle."]]
    assert encoder.query_calls == []


def test_each_text_keeps_its_own_best_sentence():
    """Regression guard for the batch offset.

    All sentences are embedded in one flat list, so an off-by-one in the slicing
    would hand one claim's sentence to another - and a snippet attached to the
    wrong claim reads as evidence while being wrong.
    """
    encoder = RecordingEncoder({"Alfa iki.": 0.9, "Beta bir.": 0.8})

    snippets = pick_snippets(
        QUESTION_VECTOR,
        ["Alfa bir. Alfa iki.", "Beta bir. Beta iki."],
        encoder,
    )

    assert snippets == ["Alfa iki.", "Beta bir."]


def test_text_without_a_terminator_is_returned_whole():
    encoder = RecordingEncoder({"Kaza yaptim": 0.5})

    assert pick_snippets(QUESTION_VECTOR, ["Kaza yaptim"], encoder) == ["Kaza yaptim"]


def test_empty_text_does_not_crash_and_never_reaches_the_encoder():
    encoder = RecordingEncoder()

    assert pick_snippets(QUESTION_VECTOR, [""], encoder) == [""]
    assert encoder.passage_calls == []


def test_a_mix_of_empty_and_real_text_stays_aligned():
    """The empty one must not consume a slot in the batch and shift the rest."""
    encoder = RecordingEncoder({"Ikinci cumle.": 0.7})

    snippets = pick_snippets(
        QUESTION_VECTOR,
        ["", "Birinci cumle. Ikinci cumle.", ""],
        encoder,
    )

    assert snippets == ["", "Ikinci cumle.", ""]
