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


def search_skills(q: str, lang: str = "en", limit: int = 20):
    """Find skills by label, most likely suggestion first."""
    term = q.strip().lower()
    if not term:
        return []

    starts, contains = [], []
    for skill_id, label in skill_index(lang):
        low = label.lower()
        if low.startswith(term):
            starts.append((skill_id, label))
        elif term in low:
            contains.append((skill_id, label))

    # Prefix matches ahead of mid-string ones, shortest label first: typing
    # "python" should offer the language before skills that merely mention it.
    starts.sort(key=lambda r: len(r[1]))
    contains.sort(key=lambda r: len(r[1]))
    return [{"id": skill_id, "label": label}
            for skill_id, label in (starts + contains)[:limit]]
