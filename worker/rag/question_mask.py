# worker/rag/question_mask.py
"""Masks the operator's question before any of it reaches a model.

Everything else on the /soru path was already covered. Result rows are masked
on the way into the narrator (sql_answer.py) and claim text is read from
`masked_text`, which was masked at ingest. The question itself was not: an
operator who typed "34 ABC 123 plakalı aracın ihbarı ne oldu?" sent that plate
to OpenAI, and docs/STATUS.md carried it as the one open PII leak in the system.

Two decisions here, both measured over eval/fixtures/rag_questions.jsonl on
2026-08-17.

**The regex layer only — no name dictionary.** The full masking pipeline touches
3 of the 100 evaluation questions and damages 2 of them: "Çağrı merkezi
transkriptinden kaç ihbar geldi?" becomes "[NAME_1] merkezi transkriptinden...",
because Çağrı is a Turkish given name as well as the word for a call. An
insurance cockpit's vocabulary overlaps the name dictionary badly, and those two
are the plainest channel questions an operator can ask. The regex layer touches
1 question - the genuine plate case - and damages none.

What that accepts: a name typed into a question still reaches the model. It is
worth little there. `claims_flat` has no name column, and text_to_sql's rule 5
refuses questions about people, so the leaked value cannot be used to retrieve
anything. Recorded as an accepted limit rather than hidden.

**A separate placeholder namespace.** Question placeholders are `[Q_PLATE_1]`,
not `[PLATE_1]`. They have to be distinguishable, because the same token would
otherwise mean two different things in one answer: the retrieval path reads
claim text masked at ingest, with its own numbering that nothing here can see or
continue, so a question's `[PLATE_1]` and a claim's `[PLATE_1]` are different
plates. Unmasking with the wrong one would print a confident wrong plate to the
operator - worse than the leak this module closes. The namespace makes the
collision impossible rather than unlikely.
"""

import re

from worker.masking.regex_rules import mask_text

# Prefix that moves a placeholder into the question's own namespace.
# "[PLATE_1]" -> "[Q_PLATE_1]".
QUESTION_PREFIX = "Q_"

# Matches both shapes: "[PLATE_1]" from claim text and "[Q_PLATE_1]" from here.
_PLACEHOLDER = re.compile(r"\[([A-Z_]+_\d+)\]")


def mask_question(question: str) -> tuple[str, list[dict]]:
    """Return the question with regex PII replaced, and the mappings to undo it.

    Mappings keep the shape the rest of the masking package uses
    (`placeholder` / `real_value` / `pii_type`), so `unmask_text` reverses this
    with no special case.
    """
    masked, mappings = mask_text(question)
    if not mappings:
        return masked, []

    renamed = []
    for mapping in mappings:
        old = mapping["placeholder"]
        new = f"[{QUESTION_PREFIX}{old[1:-1]}]"
        masked = masked.replace(old, new)
        renamed.append({**mapping, "placeholder": new})

    return masked, renamed


def has_question_placeholder(text: str) -> bool:
    """Whether `text` still carries a question placeholder.

    Used to tell "the model copied the token through, as asked" from "the model
    dropped it", which changes what a generated query means.
    """
    return any(name.startswith(QUESTION_PREFIX) for name in _PLACEHOLDER.findall(text))
