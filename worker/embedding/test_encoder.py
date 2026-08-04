# worker/embedding/test_encoder.py
"""Tests for the encoder. Nothing here loads the real model - CI has no 470 MB."""

import pytest

from worker.embedding.encoder import (
    DEFAULT_MODEL,
    EMBEDDING_DIMENSIONS,
    PASSAGE_PREFIX,
    QUERY_PREFIX,
    Encoder,
    check_dimensions,
    resolve_model_name,
)


class FakeModel:
    """Records what it was asked to encode; returns vectors of a chosen width."""

    def __init__(self, dimension: int = EMBEDDING_DIMENSIONS) -> None:
        self.dimension = dimension
        self.seen: list[str] = []

    def encode(self, sentences, **kwargs):
        self.seen.extend(sentences)
        return [[0.1] * self.dimension for _ in sentences]

    def get_sentence_embedding_dimension(self) -> int:
        return self.dimension


def test_a_query_carries_the_query_marker():
    """The prefix is the decision ADR-002 made; losing it is silent."""
    model = FakeModel()
    Encoder(model).embed_query("dolu vurdu")
    assert model.seen == [QUERY_PREFIX + "dolu vurdu"]


def test_passages_carry_the_passage_marker():
    model = FakeModel()
    Encoder(model).embed_passages(["ön cam çatladı", "tampon ezildi"])
    assert model.seen == [
        PASSAGE_PREFIX + "ön cam çatladı",
        PASSAGE_PREFIX + "tampon ezildi",
    ]


def test_a_query_is_one_vector_and_passages_are_a_list():
    encoder = Encoder(FakeModel())
    assert len(encoder.embed_query("x")) == EMBEDDING_DIMENSIONS
    vectors = encoder.embed_passages(["x", "y"])
    assert len(vectors) == 2
    assert all(len(vector) == EMBEDDING_DIMENSIONS for vector in vectors)


def test_no_text_means_no_call_and_no_vectors():
    model = FakeModel()
    assert Encoder(model).embed_passages([]) == []
    assert model.seen == []


def test_a_model_of_the_wrong_width_is_refused():
    """768 is the width of most Turkish BERT encoders - the likely wrong turn."""
    with pytest.raises(RuntimeError, match="768-dimensional"):
        check_dimensions(FakeModel(dimension=768), "some/turkish-bert")


def test_the_right_width_passes_quietly():
    assert check_dimensions(FakeModel(), DEFAULT_MODEL) is None


def test_model_name_prefers_the_argument_then_the_environment(monkeypatch):
    monkeypatch.setenv("EMBED_MODEL", "from/environment")
    assert resolve_model_name("explicit/name") == "explicit/name"
    assert resolve_model_name() == "from/environment"


def test_model_name_falls_back_to_the_adr_choice(monkeypatch):
    monkeypatch.delenv("EMBED_MODEL", raising=False)
    assert resolve_model_name() == DEFAULT_MODEL
