"""Skill lookup for the autocomplete endpoint.

Only skill search lives here. Occupation matching moved to reasoning.py,
which does it with a DL reasoner rather than a scoring heuristic.
"""
from esco_store import labels_for, sparql, uuid_of

_INDEX = {}


def skill_index(lang: str = "en"):
    """Every skill id/label pair for a language, cached in memory.

    Only ~14k rows. A SPARQL CONTAINS scan costs ~0.3s per call, far too slow
    to run on each keystroke of a typeahead; scanning this list is under a
    millisecond. Built once on first use, per language.
    """
    if lang not in _INDEX:
        # Two steps on purpose. ESCO carries skosxl:prefLabel in 28
        # languages, so skill -> label is 399k links; asking for skills and
        # labels in one pattern makes owlready2 plan from there and takes
        # minutes. Listing the skills first and constraining labels with IN
        # takes ~0.4s.
        skills = [s for s, in sparql("SELECT ?s { ?s a esco:Skill }")]
        _INDEX[lang] = sorted(
            (uuid_of(skill), label)
            for skill, label in labels_for(skills, lang).items()
        )
    return _INDEX[lang]


# Below this length a token is too generic to relax (see _token_hit): "a",
# "in", "of" would otherwise match almost every label.
_MIN_RELAX = 4


def _token_hit(token: str, words: list) -> bool:
    """Does `token` match any word of a label?

    Prefix in EITHER direction, which is what makes real phrasings work:
    ESCO says "develop", a user types "development". Requiring the label word
    to start with the token alone would miss that, because "develop" is
    shorter than what was typed. Guarded by length so short function words
    do not match everything.
    """
    for word in words:
        if word.startswith(token):
            return True
        if len(word) >= _MIN_RELAX and token.startswith(word):
            return True
    return False


def search_skills(q: str, lang: str = "en", limit: int = 20):
    """Find skills by label, most likely suggestion first.

    Three tiers, strictest first, so behaviour for a well-phrased query is
    unchanged and the looser matching only fills the remaining slots:

      1. label starts with the whole query
      2. label contains the whole query
      3. every word of the query matches some word of the label, in any order

    Tier 3 exists because a user types their own phrasing, not ESCO's.
    "game development" appears in no ESCO label as a contiguous string, but
    "develop game management plans" is plainly what they meant.
    """
    term = q.strip().lower()
    if not term:
        return []

    tokens = term.split()
    starts, contains, tokenwise = [], [], []

    for skill_id, label in skill_index(lang):
        low = label.lower()
        if low.startswith(term):
            starts.append((skill_id, label))
        elif term in low:
            contains.append((skill_id, label))
        elif len(tokens) > 1:
            # Only worth trying for multi-word queries: for a single token
            # this tier can only repeat what tier 1 and 2 already found.
            words = low.replace("(", " ").replace(")", " ").replace(",", " ").split()
            if all(_token_hit(t, words) for t in tokens):
                tokenwise.append((skill_id, label))

    # Shortest label first within each tier: typing "python" should offer the
    # language before skills that merely mention it.
    for group in (starts, contains, tokenwise):
        group.sort(key=lambda r: len(r[1]))

    return [{"id": skill_id, "label": label}
            for skill_id, label in (starts + contains + tokenwise)[:limit]]
