# worker/rag/schema.py
"""Text-to-SQL output contract - the Pydantic model the LLM must fill in.

Design doc §7.1 (the SQL path) and §7.4 (a quarter of the question set is
"should not answer"). The refusal fields exist because of §7.4: a model with no
way to decline writes a query against an invented column instead, and that is
worse than an empty result - it looks right.
"""

from pydantic import BaseModel, Field


class SqlQuery(BaseModel):
    """Türkçe bir sorudan üretilen tek SELECT sorgusu."""

    # Docstrings and descriptions in this file are not comments - pydantic ships
    # them to the model as part of the tool schema, so they are written in
    # Turkish for the model. Repo-internal notes stay in `#` comments.

    # Reasoning first, deliberately: it makes the model settle which table and
    # which time column the question needs before it commits to a query.
    reasoning: str = Field(
        description=(
            "Önce kısa muhakeme yaz: hangi tabloyu neden seçtin, zaman filtresini "
            "nasıl kurdun, belirsiz bıraktığın bir yorum varsa hangisi. En fazla 3 cümle."
        ),
    )
    answerable: bool = Field(
        description=(
            "Soru sana verilen şemayla cevaplanabiliyor mu? Şemada karşılığı olmayan "
            "bir bilgi isteniyorsa false ver."
        ),
    )
    sql: str | None = Field(
        default=None,
        description=(
            "Tek bir SELECT sorgusu, düz metin olarak. Noktalı virgül, yorum satırı "
            "veya ``` işareti koyma. answerable=false ise null bırak."
        ),
    )
    refusal_reason: str | None = Field(
        default=None,
        description=(
            "answerable=false ise, sorunun neden cevaplanamadığını Türkçe tek cümleyle "
            "yaz. answerable=true ise null bırak."
        ),
    )
