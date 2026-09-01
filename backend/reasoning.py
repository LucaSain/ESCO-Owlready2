"""Occupation recommendation by OWL reasoning.

ESCO ships occupations as SKOS individuals, which a reasoner cannot classify
anything into. So the pipeline converts data into axioms:

    1. SPARQL narrows 3,046 occupations to a shortlist that shares skills
       with the candidate.  (retrieval -- fast, approximate)
    2. Each shortlisted occupation becomes an OWL *defined class*:
           Occ_x  EQUIVALENT TO  Person and (hasSkill min N {s1 ... sk})
    3. The candidate is asserted as an individual holding skills.
    4. A DL reasoner classifies the individual.  (inference -- slow, exact)

Step 1 is not an optimisation, it is what makes step 4 terminate. Measured on
this dataset: 20 occupations classify in ~3.5s, 40 in 192s, 80 not at all.
The reasoner verifies; it does not search.
"""
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

# Must precede the owlready2 import. owlready2 exports the ontology to
# tempfile.gettempdir() before handing it to Java; /tmp is often a tmpfs, and
# a large export fills it ("No space left on device") before the reasoner
# even starts.
# Overridable because the default sits next to the source, which a
# container running as non-root cannot write to.
_TMP_DIR = Path(os.environ.get("ESCO_TMPDIR", Path(__file__).parent / "tmp"))
_TMP_DIR.mkdir(parents=True, exist_ok=True)
os.environ["TMPDIR"] = str(_TMP_DIR)
tempfile.tempdir = str(_TMP_DIR)

from owlready2 import (  # noqa: E402
    AllDifferent, OneOf, Ontology, Thing, World, reasoning, sync_reasoner_hermit,
)

from esco_store import default_world, labels_for, sparql  # noqa: E402

# MEGABYTES, not bytes -- 8*1024*1024 here would ask for an 8 TB heap and
# the JVM aborts. This is a ceiling, not a reservation, but the container
# memory limit must still exceed it or the kernel OOM-kills the JVM mid-run.
# Keep JAVA_MEMORY_MB comfortably under the container limit.
reasoning.JAVA_MEMORY = int(os.environ.get("JAVA_MEMORY_MB", "2048"))

SKILL_NS = "http://data.europa.eu/esco/skill/"

DEFAULT_SHORTLIST = 20
DEFAULT_MIN_SKILLS = 3


@dataclass
class TBox:
    """The generated ontology plus the handles later steps need."""
    world: World
    onto: Ontology
    Person: type
    hasSkill: type
    skills: dict = field(default_factory=dict)       # ESCO skill entity -> individual
    occupations: dict = field(default_factory=dict)  # generated class -> english label
    # occupation entity -> its essential skill entities. Already computed to
    # build the axioms, so exposing it lets callers derive skill/occupation
    # edges without re-querying ESCO.
    essential: dict = field(default_factory=dict)


@dataclass
class Resolution:
    """Outcome of mapping requested skill IRIs onto the TBox.

    Returned rather than printed: a caller needs to tell its user that half
    their profile was ignored, and the two failure modes mean different
    things -- `unknown` is a bad request, `unused` is normal.
    """
    individuals: list = field(default_factory=list)
    unknown: list = field(default_factory=list)  # no such skill in ESCO
    unused: list = field(default_factory=list)   # real, but no shortlisted occupation needs it


def _short(entity) -> str:
    """Last path segment of an ESCO IRI -- the bare UUID."""
    return entity.iri.rsplit("/", 1)[-1]


def _class_name(prefix: str, entity) -> str:
    return prefix + _short(entity).replace("-", "_")


def candidate_occupations(skill_ids, limit: int = DEFAULT_SHORTLIST):
    """Occupations sharing the most essential skills, best first.

    Returns [(occupation entity, overlap count)]. Labels are deliberately not
    joined in: doing so makes owlready2 plan from the 1.1M label triples.
    """
    entities = []
    for skill_id in skill_ids:
        entity = default_world[skill_id]
        if entity is not None:
            entities.append(entity)
    if not entities:
        return []

    return list(sparql(
        """SELECT ?occ (COUNT(?skill) AS ?n) {
             ?occ a esco:Occupation ; esco:relatedEssentialSkill ?skill .
             FILTER(?skill IN ??1)
           }
           GROUP BY ?occ
           ORDER BY DESC(?n)
           LIMIT ??2""",
        [entities, limit],
    ))


def build_tbox(occupations, min_skills: int = DEFAULT_MIN_SKILLS, lang: str = "en") -> TBox:
    """Turn shortlisted occupations into OWL defined classes."""
    occs = [row[0] if isinstance(row, (list, tuple)) else row for row in occupations]
    if not occs:
        raise ValueError("no occupations to build a TBox from")

    # Last read of ESCO; everything below is a small, throwaway graph.
    essential = {
        occ: [s for s, in sparql(
            "SELECT ?s { ??1 esco:relatedEssentialSkill ?s }", [occ])]
        for occ in occs
    }
    names = labels_for(occs, lang)
    all_skills = sorted({s for v in essential.values() for s in v}, key=str)

    # A fresh in-memory World: the reasoner sees a few thousand triples, not
    # ESCO's 7.9 million. Nothing here is ever written to disk.
    world = World()
    onto = world.get_ontology("http://example.org/esco-match#")

    with onto:
        class Person(Thing):
            pass

        class SkillC(Thing):
            pass

        class hasSkill(Person >> SkillC):
            pass

        skills = {s: SkillC(_class_name("s_", s)) for s in all_skills}

        # OWL makes no Unique Name Assumption: without this, six asserted
        # skills do not prove six DISTINCT ones, "min N" is never satisfied,
        # and you get zero inferences with no error. It is also O(n^2), and
        # the reason the shortlist has to stay short.
        AllDifferent(list(skills.values()))

        # equivalent_to, not is_a. A subclass axiom only reasons downwards
        # from known membership; an equivalence states necessary AND
        # sufficient conditions, which is what lets the reasoner conclude
        # "this individual IS an Occ_x" from its skills alone.
        occupations_map = {}
        for occ in occs:
            cls = type(_class_name("Occ_", occ), (Person,), {"namespace": onto})
            cls.equivalent_to = [
                Person & hasSkill.min(
                    min_skills, OneOf([skills[s] for s in essential[occ]]))
            ]
            occupations_map[cls] = names.get(occ, _short(occ))

    return TBox(world=world, onto=onto, Person=Person, hasSkill=hasSkill,
                skills=skills, occupations=occupations_map, essential=essential)


def resolve_skills(skill_ids, tbox: TBox) -> Resolution:
    """Map requested skill IRIs onto the TBox's own individuals.

    Two lookups, not string matching: the IRI resolves to an ESCO entity,
    which is the key into tbox.skills. The individuals named in the OneOf
    axioms are those exact objects -- a freshly created one with the same
    name is a different individual to the reasoner.
    """
    out = Resolution()
    for skill_id in skill_ids:
        entity = default_world[skill_id] if skill_id else None
        if entity is None:
            out.unknown.append(skill_id)
            continue
        individual = tbox.skills.get(entity)
        if individual is None:
            # Real ESCO skill, but no shortlisted occupation requires it, so
            # it appears in no OneOf and cannot affect any inference.
            out.unused.append(skill_id)
            continue
        out.individuals.append(individual)
    return out


def add_candidate(tbox: TBox, skill_ids, name: str = "candidate"):
    """Assert one individual holding the given skills."""
    resolution = resolve_skills(skill_ids, tbox)
    if not resolution.individuals:
        raise ValueError("none of the given skills are usable for matching")

    with tbox.onto:
        person = tbox.Person(name)
    person.hasSkill = resolution.individuals
    return person, resolution


def infer(tbox: TBox, candidate) -> list:
    """Classify the candidate and return the occupation labels it matched.

    sync_reasoner_* must be given the ontology explicitly -- with no argument
    it targets owlready2.default_world, which here holds 7.9M triples.
    HermiT rather than Pellet: "min N of {these}" needs nominals, and Pellet
    crashes on them with an internal ArrayIndexOutOfBoundsException.
    """
    with tbox.onto:
        sync_reasoner_hermit(tbox.onto, debug=0)

    # INDIRECT_is_a mixes named classes with anonymous class expressions
    # (the definitions themselves), which have no .name -- so test dict
    # membership first and never touch attributes before that.
    return [tbox.occupations[c] for c in candidate.INDIRECT_is_a
            if c in tbox.occupations]


def recommend(skill_ids, shortlist: int = DEFAULT_SHORTLIST,
              min_skills: int = DEFAULT_MIN_SKILLS, lang: str = "en") -> dict:
    """Full pipeline: retrieve, define, assert, classify.

    The generated world is in-memory and closed on the way out, so a request
    leaves nothing behind and the read-only ESCO store is never written to.
    """
    started = time.perf_counter()

    # Two different empty cases, and they mean different things to a caller:
    # nothing resolved is a bad request, whereas resolving fine but matching
    # no occupation is a legitimate (if unhelpful) answer.
    unknown = [s for s in skill_ids if not s or default_world[s] is None]
    if len(unknown) == len(skill_ids):
        raise ValueError("none of the given skill ids exist in ESCO")

    rows = candidate_occupations(skill_ids, shortlist)
    if not rows:
        return {"occupations": [], "shortlist": [], "skills_used": 0,
                "unknown_skill_ids": unknown, "skills_not_required": [],
                "min_skills": min_skills,
                "seconds": round(time.perf_counter() - started, 2)}

    tbox = build_tbox(rows, min_skills, lang)
    shortlist_names = labels_for([occ for occ, _ in rows], lang)
    try:
        person, resolution = add_candidate(tbox, skill_ids)
        occupations = infer(tbox, person)
        inferred = set(occupations)

        # The candidate's skills that actually reached the TBox, with labels,
        # so a client can draw the graph without a second round trip.
        used = [s for s in (default_world[i] for i in skill_ids)
                if s is not None and s in tbox.skills]
        used_set = set(used)
        skill_names = labels_for(used, lang)

        return {
            "occupations": sorted(occupations),
            # Built from `rows` and a fresh label lookup rather than by
            # zipping against tbox.occupations, which would silently depend
            # on dict insertion order matching the query result order.
            "shortlist": [
                {
                    "id": _short(occ),
                    "label": shortlist_names.get(occ, _short(occ)),
                    "shared_skills": n,
                    # Whether the reasoner actually classified the candidate
                    # into it, as opposed to merely considering it.
                    "inferred": shortlist_names.get(occ, _short(occ)) in inferred,
                    # The graph edges: which of the candidate's skills this
                    # occupation requires. Free -- tbox.essential is already
                    # in memory from building the axioms.
                    "matched_skills": [
                        _short(s) for s in tbox.essential.get(occ, ())
                        if s in used_set
                    ],
                }
                for occ, n in rows
            ],
            "skills": [
                {"id": _short(s), "label": skill_names.get(s, _short(s))}
                for s in used
            ],
            "skills_used": len(resolution.individuals),
            "unknown_skill_ids": resolution.unknown,
            "skills_not_required": resolution.unused,
            "min_skills": min_skills,
            "seconds": round(time.perf_counter() - started, 2),
        }
    finally:
        tbox.world.close()
