"""
ESCO occupation reasoner -- scaffold.

Goal
----
Load ESCO, assert a candidate individual carrying a set of skills, and run an
OWL reasoner on demand to infer which occupations that candidate matches.

How to use this file
--------------------
Every step is a TODO. The comments say what the step has to achieve, and name
the concept to look up -- they don't give you the code. Where a comment says
"GOTCHA", that is something that cost real time to discover and that you will
not find by reading the owlready2 docs, so it is stated outright.

Suggested order: 1 -> 2 -> 5 -> 6 (get end-to-end on a tiny hand-made TBox
first), then come back and do 3 and 4 properly.
"""

from owlready2 import PREDEFINED_ONTOLOGIES, Ontology, World, default_world, reasoning
import pathlib
import os
import re

_WORKDIR_PATH = pathlib.Path(os.path.abspath(__file__)).parent.resolve()

MODEL_PATH = (_WORKDIR_PATH / pathlib.Path("../backend/esco-model.rdf")).resolve()
ESCO_DATA = (_WORKDIR_PATH / pathlib.Path("../backend/esco.rdf")).resolve()
ESCO_QUAD = (_WORKDIR_PATH / pathlib.Path("./esco.sqlite")).resolve()
reasoning.JAVA_MEMORY = 6 * 1024

# PREDEFINED_ONTOLOGIES["http://purl.org/iso25964/skos-thes"] = " "

esco_world = World()

# ---------------------------------------------------------------------------
# 1. ENVIRONMENT PREP  (do this BEFORE importing owlready2)
# ---------------------------------------------------------------------------
# The reasoner is a Java subprocess. Two settings decide whether it runs at
# all, and both have caused crashes already:
#
# GOTCHA 1 -- owlready2.reasoning.JAVA_MEMORY is in MEGABYTES. Writing
#   8*1024*1024 asks for an 8 TB heap and the JVM aborts. A few thousand (MB)
#   is what you want.
#
# GOTCHA 2 -- owlready2 exports the ontology to a temp file and hands it to
#   Java. tempfile.gettempdir() is /tmp, which on this machine is a 16 GB
#   tmpfs (RAM). A large export fills it and you get "No space left on
#   device" before the reasoner even starts. Point TMPDIR somewhere on real
#   disk. Look up: os.environ["TMPDIR"], tempfile.tempdir -- and note both
#   must be set before owlready2 is imported.
#
# TODO: set the temp directory, then import owlready2, then set JAVA_MEMORY.


# ---------------------------------------------------------------------------
# 2. LOADING THE DATA
# ---------------------------------------------------------------------------
def load_esco():
    """Load the ESCO data dump into a persistent, on-disk quadstore.
    """
    esco_world.set_backend(filename=str(ESCO_QUAD))
    esco_world.get_ontology(str(ESCO_DATA)).load()
    esco_world.save()


IMPORTS_RE = re.compile(r'owl:imports\s+rdf:resource="([^"]+)"')


def stub_imports(world, path):
    """Register every owl:imports target as an already-loaded empty ontology.
    """
    iris = sorted(set(IMPORTS_RE.findall(path.read_text(encoding="utf-8"))))
    for iri in iris:
        world.get_ontology(iri).loaded = True
    return iris


def load_model():
    """Load the ESCO model ontology (the TBox).
    """
    stubbed = stub_imports(esco_world, MODEL_PATH)
    onto = esco_world.get_ontology(str(MODEL_PATH)).load()
    print(f"model: {onto.base_iri}")
    print(f"  stubbed imports  : {len(stubbed)}")
    for iri in stubbed:
        print(f"    - {iri}")
    print(f"  classes          : {len(list(onto.classes()))}")
    print(f"  object properties: {len(list(onto.object_properties()))}")
    print(f"  data properties  : {len(list(onto.data_properties()))}")
    return onto


# ---------------------------------------------------------------------------
# 3. PICKING THE OCCUPATIONS TO REASON OVER
# ---------------------------------------------------------------------------
def candidate_occupations(skill_ids: list[str], limit=20):
    """Narrow ESCO's 3,046 occupations down to a shortlist worth reasoning on.
    """
    # Resolve IRI strings -> owlready2 entities. GOTCHA 7: a str passed as a
    # SPARQL parameter becomes a *literal* and matches nothing, silently.
    skill_entities = []
    for skill_id in skill_ids:
        entity = esco_world[skill_id]
        if entity is None:
            print(f"  skipped unknown skill IRI: {skill_id}")
            continue
        skill_entities.append(entity)

    if not skill_entities:
        return []

    # Every SPARQL query needs PREFIX declarations, a form (SELECT) and a
    # body in braces. `a` is shorthand for rdf:type, and `;` continues the
    # same subject -- so this reads "?occ is an Occupation AND has ?skill".
    PREFIXES = "PREFIX esco: <http://data.europa.eu/esco/model#>"

    # STAGE 1 -- the bare pattern: every (occupation, essential skill) pair
    # in ESCO. Expect 67,600. Only a sanity check that the plumbing works;
    # delete it once you trust the query.
    # stage1 = f"""{PREFIXES}
    # SELECT ?occ ?skill
    # WHERE {{
    #     ?occ a esco:Occupation ;
    #          esco:relatedEssentialSkill ?skill .
    # }}"""
    # print("  stage 1 (all pairs)      :", len(list(esco_world.sparql(stage1))))

    # STAGE 2 -- restrict ?skill to the candidate's own. ??1 is owlready2's
    # parameter placeholder; pass a Python list and it works with IN. Never
    # interpolate values into query text with an f-string.
    stage2 = f"""{PREFIXES}
    SELECT ?occ ?skill
    WHERE {{
        ?occ a esco:Occupation ;
             esco:relatedEssentialSkill ?skill .
        FILTER(?skill IN ??1)
    }}"""
    rows = list(esco_world.sparql(stage2, [skill_entities]))
    print("  stage 2 (only my skills) :", len(rows))

    # sparql() returns a GENERATOR -- wrap in list() or iterate, or you just
    # print the generator object. Each row is a list of the SELECT columns.
    for occ, skill in rows[:3]:
        print(f"      {occ}  <-  {skill}")

    # TODO STAGE 3 -- collapse to one row per occupation with a count.
    #   Add GROUP BY ?occ and project the count instead of ?skill. An
    #   aggregate in SELECT must be wrapped and aliased -- the
    #   (COUNT(...) AS ?n) form -- and GROUP BY goes AFTER the closing brace.
    #   Decide COUNT(?skill) vs COUNT(DISTINCT ?skill) by comparing both.
    #   Expect 57 rows for the 6-skill fixture.

    stage3 = f"""{PREFIXES}
    SELECT ?occ (COUNT(?skill) as ?n)
    WHERE {{
        ?occ a esco:Occupation ;
             esco:relatedEssentialSkill ?skill .
        FILTER(?skill IN ??1)
    }}
    GROUP BY ?occ
    """
    rows = list(esco_world.sparql(stage3, [skill_entities]))
    print("  stage 3 (grouped)        :", len(rows), "occupations")

    # TODO STAGE 4 -- ORDER BY DESC(?n), LIMIT, and return the shortlist.
    #   Expect top counts 6, 6, 5, 3, 2, 1, ...
    #   Do NOT join labels in here (the 37s trap) -- fetch labels for the
    #   surviving `limit` occupations in a second query.
    return rows

# ---------------------------------------------------------------------------
# 4. BUILDING THE TBox  -- this is the core of the approach
# ---------------------------------------------------------------------------
def build_tbox(occupations):
    """Turn each shortlisted occupation into an OWL *defined class*.

    This is the step that makes reasoning possible. ESCO ships occupations as
    individuals, and a reasoner cannot classify anything into an individual.
    You are converting data into axioms.

    The shape you are aiming for, per occupation:

        Occ_x  EQUIVALENT TO  Person and (hasSkill min N {skill1 ... skillK})

    "Equivalent to", not "subclass of". A subclass axiom only lets the
    reasoner reason downwards from a known membership; an equivalence gives
    necessary AND sufficient conditions, which is what lets it conclude
    "this individual IS an Occ_x" from the skills alone. Getting this wrong
    is the single most common reason this technique appears to do nothing.

    Look up, in owlready2:
      - declaring classes and properties inside a `with onto:` block
      - equivalent_to
      - OneOf  (the {a, b, c} enumeration -- "one of these specific skills")
      - a property restriction with a minimum cardinality and a filler class
      - AllDifferent

    GOTCHA 8 -- without AllDifferent over the skill individuals you will get
      ZERO inferences and no error. OWL makes no Unique Name Assumption, so
      asserting six skills does not prove the candidate has six DISTINCT
      ones; they could all be the same thing, so "min 3" is never satisfied.
      You must assert that the skill individuals are pairwise different.
      This is also the main cost driver -- it is O(n^2) -- which is why the
      shortlist in step 3 matters so much.

    Design decision you have to make: what is N? N = all essential skills is
    exact matching and almost nobody will match. A small N is forgiving but
    vague. This threshold is the knob your results live or die by, and it is
    worth writing down why you chose it.
    """
    raise NotImplementedError


# ---------------------------------------------------------------------------
# 5. THE CANDIDATE
# ---------------------------------------------------------------------------
def add_candidate(onto, skill_ids):
    """Assert one individual holding the given skills.

    Look up: creating an individual of a class in owlready2, and assigning a
    list to an object property.

    The skill individuals here must be the SAME objects used in the class
    axioms in step 4. If you create fresh ones, nothing will match, because
    the enumerations in those axioms name specific individuals.
    """
    raise NotImplementedError


# ---------------------------------------------------------------------------
# 6. REASONING ON DEMAND
# ---------------------------------------------------------------------------
def infer(onto, candidate):
    """Run the reasoner and read back which occupation classes the candidate
    now belongs to.

    Look up: sync_reasoner_hermit / sync_reasoner_pellet, and the difference
    between an individual's asserted `is_a` and its INDIRECT_is_a.

    GOTCHA 9 -- call these with the ontology (or world) as the FIRST
      argument. With no argument they fall back to owlready2.default_world.
      If your ESCO data happens to be there, you have just pointed a DL
      reasoner at 7.9 million triples and the JVM will die.

    GOTCHA 10 -- use HermiT, not Pellet, for this. "min N of {these}" needs
      nominals, and Pellet crashes on it with an internal
      ArrayIndexOutOfBoundsException in DisjunctionBranch.tryBranch. That is
      a Pellet bug, not your axioms.

    The reasoner runs as a fresh JVM each call and re-classifies the whole
    TBox every time, which is most of the ~8.7s. If that becomes the
    bottleneck, the direction to research is a persistent reasoner via the
    OWL API that classifies once and only *realizes* new individuals per
    request -- but get it correct before you make it fast.
    """
    raise NotImplementedError


# ---------------------------------------------------------------------------
# TEST FIXTURE  -- real ESCO IRIs, so you have a known-good input
# ---------------------------------------------------------------------------
# The six essential skills of "assistant clinical psychologist". Feeding these
# back in MUST rank that occupation top -- they are literally its own skills.
FIXTURE_SKILLS = [
    "http://data.europa.eu/esco/skill/e9e08a59-f697-434c-a955-39623650be9d",  # assess healthcare users' risk for harm
    "http://data.europa.eu/esco/skill/b9b572bf-5e50-4588-8aa0-a42a49332467",  # psychological interventions
    "http://data.europa.eu/esco/skill/98eb1f3b-3480-416b-bd4b-811946f7e347",  # comply with quality standards related to healthcare practice
    "http://data.europa.eu/esco/skill/110833ee-c4f1-4856-9b7f-7e49ffda537f",  # apply psychological intervention strategies
    "http://data.europa.eu/esco/skill/8f5d6a1b-32fa-4c3f-b3d6-5f070d2e0f74",  # therapy in health care
    "http://data.europa.eu/esco/skill/604fa3e6-bc8d-423e-b7e8-c0ba2416eaa4",  # work with patterns of psychological behaviour
]

# Expected result for FIXTURE_SKILLS, so you can check yourself:
#   57 occupations, top counts 6, 6, 5, 3, 2, 1, ...
#   6 assistant clinical psychologist / 6 clinical psychologist
#   5 health psychologist / 3 psychotherapist / 2 psychologist


def labels_for(entities, lang="en"):
    """{entity: english label} -- a HARNESS helper so output is readable.

    ESCO uses SKOS-XL: label text is not on the concept, it hangs off a
    skosxl:Label node via skosxl:prefLabel, then skosxl:literalForm.

    Note the shape -- this is the "second query" pattern. It constrains ?e
    with IN to the handful of entities you already have, rather than joining
    labels into the big counting query, which would make owlready2 plan from
    the 1.1M skosxl:Label triples (the 37s trap).
    """
    if not entities:
        return {}
    q = """PREFIX skosxl: <http://www.w3.org/2008/05/skos-xl#>
    SELECT ?e ?form
    WHERE {
        ?e skosxl:prefLabel ?lb .
        ?lb skosxl:literalForm ?form .
        FILTER(?e IN ??1 && LANG(?form) = ??2)
    }"""
    return {e: str(f) for e, f in esco_world.sparql(q, [list(entities), lang])}


# ---------------------------------------------------------------------------
# 7. MAIN
# ---------------------------------------------------------------------------
def main():
    """Wire the steps together.

    A reasonable first milestone, before any of the ESCO loading works:
    hand-write two or three occupation classes and four or five skill
    individuals yourself, assert a candidate, and get infer() to print a
    correct answer. That proves you understand the axioms. Only then plug in
    the real data, where a wrong answer is much harder to debug.

    Sanity check for later: a candidate holding several skills of "clinical
    psychologist" should come back as clinical psychologist, psychotherapist
    and speech and language therapist. If you get an empty list, re-read
    GOTCHA 8.s
    """
    print(f"model : {MODEL_PATH}")
    print(f"data  : {ESCO_DATA}")
    print(f"store : {ESCO_QUAD}\n")

    load_esco()
    print(f"data loaded: {len(esco_world.graph):,} triples\n")
    load_model()

    print("\ncandidate_occupations(FIXTURE_SKILLS):")
    rows = candidate_occupations(FIXTURE_SKILLS)

    # stage 3 returns [occupation, count] pairs. Sorting/limiting is still in
    # Python here -- move it into the query (ORDER BY / LIMIT) for stage 4.
    ranked = sorted(rows, key=lambda r: -r[1])[:10]
    names = labels_for([occ for occ, _ in ranked])
    print("\n  top 10 by overlap:")
    for occ, n in ranked:
        print(f"    {n}  {names.get(occ, occ)}")


if __name__ == "__main__":
    main()
