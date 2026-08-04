# worker/embedding/encoder.py
"""Local sentence embeddings for RAG retrieval and free-text scoring.

ADR-002: intfloat/multilingual-e5-small, 384 dimensions, running on this machine
rather than behind an API. Nothing here reaches the network once the model is on
disk.

e5 was trained with instruction prefixes, and text embedded without them is
silently worse - the failure leaves no trace in any output. That is why the
prefix is applied here and callers never hand raw text to the model.
"""

import os
from typing import Protocol

DEFAULT_MODEL = "intfloat/multilingual-e5-small"

# Fixed by the schema, not by preference: VECTOR(384) in the migration and in
# api/models/db.py:69. A model of another width produces rows Postgres rejects,
# and it rejects them far from here.
EMBEDDING_DIMENSIONS = 384

# e5's two markers. Asymmetric retrieval - a question against claim text - uses
# one of each. A symmetric comparison, such as eval scoring one description
# against another, uses the query marker on both sides. That is e5's own rule,
# not a shortcut.
QUERY_PREFIX = "query: "
PASSAGE_PREFIX = "passage: "


class SentenceEncoder(Protocol):
    """The slice of SentenceTransformer this module uses.

    Declared so tests can pass a stub. Loading the real model costs a 470 MB
    download and about a second of startup, and CI has neither.
    """

    def encode(self, sentences: list[str], **kwargs) -> object: ...

    def get_sentence_embedding_dimension(self) -> int | None: ...


def resolve_model_name(name: str | None = None) -> str:
    """Explicit argument, then EMBED_MODEL, then the model ADR-002 chose."""
    return name or os.environ.get("EMBED_MODEL") or DEFAULT_MODEL


def check_dimensions(model: SentenceEncoder, name: str) -> None:
    """Refuse a model whose vectors will not fit the column.

    Raised at load time on purpose. Without it the wrong model encodes happily
    and the first sign of trouble is an INSERT failing inside the pipeline, with
    nothing in the message pointing back at the model choice.
    """
    dimension = model.get_sentence_embedding_dimension()
    if dimension != EMBEDDING_DIMENSIONS:
        raise RuntimeError(
            f"{name} produces {dimension}-dimensional vectors, but the schema is "
            f"VECTOR({EMBEDDING_DIMENSIONS}). Changing that width means a migration "
            "and re-embedding every claim (ADR-001)."
        )


def load_model(name: str | None = None) -> SentenceEncoder:
    """Load the configured model, refusing one of the wrong width.

    The import sits inside the function: sentence-transformers pulls torch, and
    a module-level import would make every worker process pay for it whether or
    not it ever embeds anything.
    """
    from sentence_transformers import SentenceTransformer

    name = resolve_model_name(name)
    model = SentenceTransformer(name)
    check_dimensions(model, name)
    return model


class Encoder:
    """Turns Turkish claim text into vectors, with e5's prefixes applied here.

    Build once and reuse: loading the model takes about a second, and a process
    that reloads it per call spends all its time doing that.
    """

    def __init__(self, model: SentenceEncoder | None = None) -> None:
        self.model = model if model is not None else load_model()

    def _encode(self, texts: list[str], prefix: str) -> list[list[float]]:
        """Prefix, encode, and hand back plain floats.

        Vectors come back normalized, so a dot product is already the cosine
        similarity - which is what both pgvector and the eval scoring want.
        """
        if not texts:
            return []
        vectors = self.model.encode(
            [prefix + text for text in texts],
            normalize_embeddings=True,
            batch_size=64,
            show_progress_bar=False,
        )
        return [[float(value) for value in vector] for vector in vectors]

    def embed_query(self, text: str) -> list[float]:
        """Embed text being searched *with*.

        Also used for both sides of a symmetric comparison - eval scoring one
        description against another - because e5 marks that case as a query too.
        """
        return self._encode([text], QUERY_PREFIX)[0]

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        """Embed the text being searched *through*: claim text going to the store."""
        return self._encode(list(texts), PASSAGE_PREFIX)
