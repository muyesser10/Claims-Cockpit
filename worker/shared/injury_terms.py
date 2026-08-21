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

                                    original      08-09       08-17
  corpus recall                        80/80      80/80       80/80
  corpus precision                     98.8%       100%        100%
  fixture, ASCII-typed injuries          0/5        4/5         4/5
  fixture, injury-free controls         9/15       5/15        1/15
  fixture, all hard positives           0/19       4/19        4/19

The 08-17 column is CONTEXT_TERMS, below: four of the five remaining false fires
were a medical word naming a place or a collision target, and qualifying them
removed all four without moving a single recall figure. The one left is "ölüm
virajında kaza yaptım" - an idiom for a dangerous bend, and not this layer's to
fix: the model calls that one critical on its own, so the OR fires either way.

The last row is the honest one. 14 of the 19 are phrased through medical context
alone - "112'yi aradık", "dikiş attırmak zorunda kaldım", "acilde dört saat
bekledik" - and no term list reaches those without inventing terms the corpus
cannot show to be safe. That gap is a property of the approach, not a bug to
close: the LLM classifier carries those, and this layer is what still works when
it does not.
"""

import re
from collections.abc import Callable

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
    # These four are context, not injury: they name medical involvement, and a
    # vehicle can hit any of them without anyone being hurt. See CONTEXT_TERMS.
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
    # Medical process and aftermath. These name what was done for a person
    # rather than what happened to them, and CONTEXT_TERMS is why they can be
    # here at all: bare they are compound modifiers ("yoğun bakım ünitesi",
    # "tomografi cihazı"), inflected they are a person being treated ("yoğun
    # bakıma alındı", "tomografisi çekildi").
    #
    # Added 2026-08-17 after three prompt versions failed to reach this family:
    # blind recall on it sat near 44% for v2, v3 and v4 alike, on sentences no
    # person would hesitate over. What the prompt could not learn, grammar can -
    # for the inflected half of the family. The bare half ("ameliyat oldum",
    # "tedavi gördüm") stays out of reach and is measured separately.
    "ameliyat",
    "tomografi",
    "röntgen",
    "fizyoterapi",
    "yoğun bakım",
    "tedavi",
    "taburcu",
    "korse",
    "serum",
    "pansuman",
    "dikiş",
    "istirahat",
    "iş göremezlik",
    "ağrı kesici",
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

# Terms that name medical involvement rather than an injury. Alone they assert
# nothing: a hospital is also a car park, an ambulance is also something you can
# rear-end, and "acil servis" is also a sign to drive into. Measured over
# eval/fixtures/injury_phrasings.jsonl, these four produced four of the five
# false criticals in the injury-free control group - and the deterministic rule
# is an OR with the model, so a false fire here cannot be corrected downstream.
#
# Deleting them was the obvious fix and is the wrong one. Over the 1000-record
# corpus they carry no recall at all (80/80 with and without, measured
# 2026-08-17), but the corpus never phrases an injury through them; the
# hand-written cases below do, and there the term is the only evidence:
#   "ambulans çağırdık"   "hastaneye kaldırıldı"   "eşim acil servise kaldırıldı"
# So they are kept and qualified instead.
CONTEXT_TERMS = frozenset(
    {
        "hastane",
        "ambulans",
        "sedye",
        "acil servis",
        "ameliyat",
        "tomografi",
        "röntgen",
        "fizyoterapi",
        "yoğun bakım",
        "tedavi",
        "taburcu",
        "korse",
        "serum",
        "pansuman",
        "dikiş",
        "istirahat",
        "iş göremezlik",
        "ağrı kesici",
    }
)

# A context term qualifies two ways, and both are needed - each covers what the
# other misses.
#
# 1. The term is inflected. In a Turkish noun-noun compound the modifier takes no
#    suffix, and every false positive has exactly that shape: *hastane* otoparkı,
#    *ambulans* yolu, *acil servis* tabelası, *sedye* taşıyan araç. The noun names
#    a thing in the world there. A suffix means it is participating in the
#    sentence instead - "hastanede", "hastaneye", "acil servise" - which is a
#    person being somewhere or taken somewhere. This is grammar rather than a word
#    list, which is why it is the first check.
_INFLECTED = re.compile(r"^[a-z]")

# 2. A care action follows. Turkish subjects are bare too, so inflection alone
#    would drop "ambulans çağırdık" and "ambulans geldi", where the term is the
#    subject and the evidence is the verb. Stems, because the suffix carries the
#    person rather than the meaning ("çağırdık", "çağrıldı", "kaldırıldı").
#
#    "taşı-" is deliberately absent. "Sedye taşıyan bir araca çarptım" is a
#    collision with a vehicle and is the exact shape this guard exists to stop;
#    admitting the stem would readmit that false positive to catch a phrasing
#    ("hastaneye taşındı") that the dative in check 1 already covers.
#    The second group is treatment rather than transport, and closes the shape
#    holdout3 measured: a bare term with the verb doing the work ("korse
#    taktılar", "röntgen çektiler", "istirahat yazdılar"). Each stem is narrow on
#    purpose. "baglad" rather than "bagla", because "bağlantı" folds to
#    "baglanti" and "hastane bağlantı yolu" is a road, not a patient. "yapt" and
#    "at" are absent for the same reason at greater cost: "kaza yaptım" and
#    "hasar attı" would turn every term in the window into an injury, so
#    "ameliyat yaptılar" and "dikiş attılar" stay unreachable here and are left
#    to the model.
_CARE_ACTION = re.compile(
    r"(cagir|cagr|geld|gelm|kaldir|gotur|sevk|mudahale|takt|verd|cekt|baglad|yazd)"
)

# How far past the term to look for the verb. Turkish puts it last, so it follows
# the noun it acts on.
_CARE_WINDOW = 30


def _context_qualifies(guards: str, end: int) -> bool:
    """Whether a CONTEXT_TERMS match at `end` is about a person, not a place."""
    tail = guards[end:]
    return bool(_INFLECTED.match(tail) or _CARE_ACTION.search(tail[:_CARE_WINDOW]))


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
# The bare particle needs a space in front of it. Turkish writes the question
# particle as its own word ("korse mi?") and the possessive/accusative suffix
# attached ("korsemi"), and the two are the same letters - so a pattern allowing
# zero spaces read "Korsemi çıkarmama izin vermediler" as a question and threw
# the signal away. Found by the holdout3 split on "Fizyoterapimi" and "Korsemi",
# and it applies to every term, not only the ones added alongside it.
_INTERROGATIVE = re.compile(r"^\s*(var\s*mi|var\s*miydi|oldu\s*mu)|^\s+(mi|mu)\b")

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


def _asserts(
    haystack: str,
    guards: str,
    needle: str,
    *,
    requires: Callable[[str, int], bool] | None = None,
) -> bool:
    """Whether `haystack` claims `needle` happened, rather than merely spelling it.

    A term counts when it starts a word, is not negated on either side, is not a
    bare form label, and is not part of a question.

    `guards` is the ASCII-folded haystack and is where the four checks read
    their context. Folding preserves length, so an offset found in `haystack`
    points at the same place in `guards`; separating them lets a term be matched
    with its Turkish letters intact while the guards stay spelling-independent.

    `requires` is the extra condition a context term has to meet
    (_context_qualifies). Checked per occurrence rather than per text, so one
    mention that fails it does not bury a later one that passes: "Ambulans yolu
    kapalıydı, sonra ambulans çağırdık" is still an injury.
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
        if requires is not None and not requires(guards, match.end()):
            continue

        return True

    return False


def find_injury_signals(text: str) -> list[str]:
    """The injury terms `text` actually asserts, in INJURY_TERMS order.

    Anything returned here is treated as an injury by every caller, so the bar is
    "the text says this happened" rather than "these letters appear".

    Erring towards a false positive is deliberate where the two rules disagree:
    the cost of one unnecessary critical is an operator's minute, and the cost of
    a missed one is the case this system exists to catch. That asymmetry does not
    extend to CONTEXT_TERMS, which name medical involvement rather than harm and
    need a care action beside them to count.
    """
    normalized = _normalize_tr(text)
    folded = _fold_tr_ascii(normalized)
    found: list[str] = []

    for term in INJURY_TERMS:
        needle = _normalize_tr(term)
        requires = _context_qualifies if term in CONTEXT_TERMS else None
        if _asserts(normalized, folded, needle, requires=requires):
            found.append(term)
        elif term not in NEVER_FOLD_TERMS and _asserts(
            folded, folded, _fold_tr_ascii(needle), requires=requires
        ):
            found.append(term)

    return found
