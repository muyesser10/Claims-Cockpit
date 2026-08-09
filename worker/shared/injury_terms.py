# worker/shared/injury_terms.py
"""Single source of truth for injury-term matching.

Three independent consumers need the same word list and the same Turkish-safe
comparison, so all of it lives here instead of being duplicated per module:
  - worker/pipeline.py                    step_classify's deterministic
                                           injury -> critical trigger (CLAUDE.md S1)
  - worker/validation/validator.py        validate()'s cross-check between
                                           extraction's `injury` field and the raw text
  - worker/classification/classifier.py   the override over the model's urgency

Use `find_injury_signals()` rather than testing `term in text` directly. Measured
over the 1000-record corpus on 2026-08-04, plain substring matching found all 80
real injuries and another 353 that were not there - a precision of 18.5%. Three
things went wrong, and all three are handled below:

  substring       Turkish is agglutinative and these terms are short. "bölüm"
                  contains "ölü"; "mekan", "imkan" and "dükkan" contain "kan".
  negation        "kimse yaralanmadı" and "Yaralanma: hayır" both contain
                  "yaralanma", and both mean the opposite of a match.
  empty field     web_form messages carry a literal "Yaralanma:" label whose
                  value is sometimes blank. The label is not a signal.
  question        a call transcript is an agent asking "Aracınızda yaralanan
                  var mı?". The word is there; the injury is not.

Recall is the number that must not move: a missed injury is the one error this
system cannot make (CLAUDE.md §7, >= 97%).

Measured over the same 1000-record corpus on 2026-08-09, and over
eval/fixtures/injury_phrasings.jsonl - 34 phrasings written by hand precisely
because the corpus does not contain them:

                                        before      after
  corpus recall                         80/80       80/80
  corpus precision                      98.8%       100%
  fixture, ASCII-typed injuries          0/5         4/5
  fixture, injury-free controls          9/15        5/15
  fixture, all hard positives            0/19        4/19

The last row is the honest one. 14 of the 19 are phrased through medical context
alone - "112'yi aradık", "dikiş attırmak zorunda kaldım", "acilde dört saat
bekledik" - and no term list reaches those without inventing terms the corpus
cannot show to be safe. That gap is a property of the approach, not a bug to
close: the LLM classifier carries those, and this layer is what still works when
it does not.
"""

import re

INJURY_TERMS = (
    "yaralı",
    "yaralanma",
    "yaralandı",
    # Added: the corpus never phrases it this way, but people do - "kazada
    # yaralanan oldu". Written out as an inflection rather than shortening the
    # stem to "yaralan", which was tried and is wrong twice over: the match ends
    # mid-word, and the suffix that follows flips the meaning per term
    # ("yaralanma" + "dı" is a denial, "yaralan" + "dı" is an injury). Measured
    # over the corpus, the stem form cost 5 points of recall.
    "yaralanan",
    # Was a bare "kan". Turkish is agglutinative and three letters are not a
    # word: "kanal", "kanaat" and "kanatlı" all start with it, and the
    # word-start guard cannot tell them apart. These are the forms that assert
    # bleeding.
    "kanama",
    "kanıyor",
    "kan kayb",
    "hastane",
    "ambulans",
    "ölü",
    "ölüm",
    "sedye",
    "kırık",
    # Was a bare "bilinç", which matched "bilinçli olarak" - a phrase about
    # doing something deliberately, not about losing consciousness.
    "bilinç kayb",
    "bilinci kapalı",
    "bilinçsiz",
    "acil servis",
)

# Terms are also matched with their Turkish letters folded to ASCII, for text
# typed on a keyboard without them ("kolumda kirik var") - except these two.
#
# Stated as an exception list rather than an allow-list because the exception is
# the interesting part. "ölü" folds to "olu", which starts 321 words in the
# corpus that have nothing to do with death: "oluştu", "oluşan", "olursanız".
# Every other term folds to a string long or distinctive enough not to prefix a
# common word.
#
# "kanlı" was dropped from the list entirely for the same kind of reason: it
# prefixes "Kanlıca", an İstanbul district, with or without folding. Bleeding is
# already asserted by "kanama" and "kan kayb".
NEVER_FOLD_TERMS = frozenset({"ölü", "ölüm"})


# A term must start a word. Only the left edge is checked: Turkish suffixes
# attach to the right, so "yaralıydı" and "hastaneye" have to keep matching.
_WORD_START = r"(?<![0-9a-zçğıöşü])"

# Every guard below is matched against ASCII-folded text, so each is written
# once in its folded form. Before, they carried both spellings by hand
# ("hayır|hayir", "olmadı|olmadi") and the list was one variant short of
# complete - which is how "var mı", folded to "var mi", walked past the
# question guard and turned an agent's question into a reported injury.

# Negation as a separate word, looked for on both sides of the term: "yaralanan
# yok", "Yaralanma: hayır", "kimse yaralanmadı" (where "hayır" sits ahead of it).
_NEGATION = re.compile(r"(yok|hayir|yoktu|olmadi|degil)")

# Negation as a Turkish suffix on the term itself: -madı/-medi, -maz/-mez,
# -mayan/-meyen. "yaralanma" + "dı" is one word meaning it did not happen.
_NEGATION_SUFFIX = re.compile(r"^(di|du|z|yan|yen|yacak|yecek)")

# A form label with nothing after it: "Yaralanma:" followed by end of line.
_EMPTY_FIELD = re.compile(r"^\s*:\s*(\n|$)")

# A question is not a claim. Call transcripts are the agent asking - "Aracınızda
# yaralanan var mı?" - and the term in the question was being read as the
# customer reporting one. The third category beside negation and the empty
# label: the text contains the word without asserting the thing.
_INTERROGATIVE = re.compile(r"^\s*(var\s*mi|var\s*miydi|oldu\s*mu|mi\b|mu\b)")

# How far to look for a negating word on either side. Wide enough to cover
# "hayır, kazada kimse yaralanmadı", narrow enough not to reach the next
# sentence in a transcript.
_NEGATION_WINDOW = 30


_ASCII_FOLD = str.maketrans("çğıöşü", "cgiosu")


def _normalize_tr(text: str) -> str:
    """Turkish-safe lowercase.

    str.lower() applies the ASCII I -> i rule, so "YARALI".lower() ==
    "yarali" (dotless ı lost) and never matches "yaralı". Turkish has two
    I/i pairs (İ/i and I/ı); fix both by hand before lowercasing the rest.
    """
    return text.replace("I", "ı").replace("İ", "i").lower()


def _fold_tr_ascii(text: str) -> str:
    """Turkish letters to their ASCII look-alikes, one character for one.

    Length-preserving on purpose, so an offset into the folded string still
    points at the same place in the string it came from.
    """
    return text.translate(_ASCII_FOLD)


def _asserts(haystack: str, guards: str, needle: str) -> bool:
    """Whether `haystack` claims `needle` happened, rather than merely spelling it.

    A term counts when it starts a word, is not negated on either side, is not a
    bare form label, and is not part of a question.

    `guards` is the ASCII-folded haystack and is where the four checks read
    their context. Folding preserves length, so an offset found in `haystack`
    points at the same place in `guards`; separating them lets a term be matched
    with its Turkish letters intact while the guards stay spelling-independent.
    """
    for match in re.finditer(_WORD_START + re.escape(needle), haystack):
        after = guards[match.end() : match.end() + _NEGATION_WINDOW]
        before = guards[max(0, match.start() - _NEGATION_WINDOW) : match.start()]

        if _NEGATION.search(after) or _NEGATION.search(before):
            continue
        if _NEGATION_SUFFIX.match(after):
            continue
        if _EMPTY_FIELD.match(guards[match.end() :]):
            continue
        if _INTERROGATIVE.match(after):
            continue

        return True

    return False


def find_injury_signals(text: str) -> list[str]:
    """The injury terms `text` actually asserts, in INJURY_TERMS order.

    Anything returned here is treated as an injury by every caller, so the bar is
    "the text says this happened" rather than "these letters appear".

    Erring towards a false positive is deliberate where the two rules disagree:
    the cost of one unnecessary critical is an operator's minute, and the cost of
    a missed one is the case this system exists to catch.
    """
    normalized = _normalize_tr(text)
    folded = _fold_tr_ascii(normalized)
    found: list[str] = []

    for term in INJURY_TERMS:
        needle = _normalize_tr(term)
        if _asserts(normalized, folded, needle):
            found.append(term)
        elif term not in NEVER_FOLD_TERMS and _asserts(folded, folded, _fold_tr_ascii(needle)):
            found.append(term)

    return found
