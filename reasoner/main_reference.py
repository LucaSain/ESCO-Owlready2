"""
ESCO occupation reasoner
"""

from owlready2 import (AllDifferent, Ontology, OneOf, PREDEFINED_ONTOLOGIES, Thing,
                       World, default_world, reasoning)
from dataclasses import dataclass, field
import pathlib
import os
import re

from owlready2.sparql.parser import sync_reasoner_hermit

_WORKDIR_PATH = pathlib.Path(os.path.abspath(__file__)).parent.resolve()

MODEL_PATH = (_WORKDIR_PATH / pathlib.Path("../backend/esco-model.rdf")).resolve()
ESCO_DATA = (_WORKDIR_PATH / pathlib.Path("../backend/esco.rdf")).resolve()
ESCO_QUAD = (_WORKDIR_PATH / pathlib.Path("./esco.sqlite")).resolve()
reasoning.JAVA_MEMORY = 6 * 1024

# PREDEFINED_ONTOLOGIES["http://purl.org/iso25964/skos-thes"] = " "

esco_world = World()

def load_esco():
    """
    Load the ESCO data dump into a persistent, on-disk quadstore.
    """
    # read_only=True opens sqlite with mode=ro, so a stray write fails with
    # "attempt to write a readonly database" instead of quietly mutating the
    # store. Queries are unaffected.
    #
    # No .load() and no .save(): the quadstore is already built, so opening
    # it IS the whole job. Parsing esco.rdf is a one-off ingest -- see
    # ingest_esco() below -- not something a run should ever do.
    esco_world.set_backend(filename=str(ESCO_QUAD), read_only=True)
    return esco_world


def ingest_esco():
    """One-off: parse esco.rdf into the quadstore. NOT called by main().

    Run this by hand only when ESCO_QUAD does not exist, or to rebuild it
    after deleting the file. It is the only code here that writes anything.
    """
    if ESCO_QUAD.exists():
        raise FileExistsError(f"{ESCO_QUAD} exists -- delete it to rebuild")
    esco_world.set_backend(filename=str(ESCO_QUAD))
    esco_world.get_ontology(str(ESCO_DATA)).load()
    esco_world.save()
    print(f"ingested {len(esco_world.graph):,} triples")


IMPORTS_RE = re.compile(r'owl:imports\s+rdf:resource="([^"]+)"')


def stub_imports(world, path):
    """
    Register every owl:imports target as an already-loaded empty ontology.
    """
    iris = sorted(set(IMPORTS_RE.findall(path.read_text(encoding="utf-8"))))
    for iri in iris:
        world.get_ontology(iri).loaded = True
    return iris


def load_model():
    """
    Load the ESCO model ontology (the TBox).
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
    """
    Narrow ESCO's 3,046 occupations down to a shortlist worth reasoning on.
    """
    # Resolve IRI strings -> owlready2 entities.
    skill_entities = []
    for skill_id in skill_ids:
        entity = esco_world[skill_id]
        if entity is None:
            print(f"  skipped unknown skill IRI: {skill_id}")
            continue
        skill_entities.append(entity)

    if not skill_entities:
        return []


    PREFIXES = "PREFIX esco: <http://data.europa.eu/esco/model#>"

    query = f"""{PREFIXES}
    SELECT ?occ (COUNT(?skill) as ?n)
    WHERE {{
        ?occ a esco:Occupation ;
             esco:relatedEssentialSkill ?skill .
        FILTER(?skill IN ??1)
    }}
    GROUP BY ?occ
    ORDER BY DESC(?n)
    LIMIT ??2
    """
    rows = list(esco_world.sparql(query, [skill_entities,limit]))
    return rows

def _short(entity):
    """Last path segment of an ESCO IRI -- the bare UUID."""
    return entity.iri.rsplit("/", 1)[-1]


@dataclass
class TBox:
    world: World
    onto: Ontology
    Person: type
    hasSkill: type
    skills: dict = field(default_factory=dict)       # ESCO skill entity -> individual
    occupations: dict = field(default_factory=dict)


def build_tbox(occupations, min_skills=3):
    """
    Turn each shortlisted occupation into an OWL *defined class*.
    """

    occs = [row[0] if isinstance(row, (list, tuple)) else row for row in occupations]
    if not occs:
        raise ValueError("no occupations to build a TBox from")

    # Essential Skills
    essential = {}
    for occ in occs:
        essential[occ] = [
            s for s, in esco_world.sparql(
                "PREFIX esco: <http://data.europa.eu/esco/model#>\n"
                "SELECT ?s WHERE { ??1 esco:relatedEssentialSkill ?s }", [occ])
        ]
    names = labels_for(occs)
    all_skills = sorted({s for v in essential.values() for s in v}, key=str)

    world = World()
    onto = world.get_ontology("http://example.org/esco-match#")

    with onto:
        class Person(Thing):
            pass

        class SkillC(Thing):
            pass

        class hasSkill(Person >> SkillC): # points to a skill
            pass

        # UUID's dashes become underscores.
        skills = {
            s: SkillC("s_" + _short(s).replace("-", "_"))
            for s in all_skills
        }

        # world.
        AllDifferent(list(skills.values()))


        occ_classes = {}
        for occ in occs:
            cls = type("Occ_" + _short(occ).replace("-", "_"), (Person,),
                       {"namespace": onto})
            cls.equivalent_to = [
                Person & hasSkill.min(min_skills,
                                      OneOf([skills[s] for s in essential[occ]]))
            ]
            occ_classes[cls] = names.get(occ, str(occ))

    print(f"  TBox: {len(occ_classes)} occupations, {len(skills)} skills, "
          f"threshold min_skills={min_skills}")
    return TBox(world=world, onto=onto, Person=Person, hasSkill=hasSkill,
                skills=skills, occupations=occ_classes)


def toRegisteredSkills(skill_ids, tbox:TBox):
    skills = [  ]

    for skill_id in skill_ids:
        if(skill_id==None):
            print("No Skill!")
            continue

        skill_entity = esco_world[skill_id]

        if(skill_entity is None):
            print("Skill Entity Not Registered in ESCO!")
            continue

        individual_skill = tbox.skills.get(skill_entity)

        if(individual_skill is None):
            print("Indivudal Skill not Found in TBOX!")
            continue

        skills.append(individual_skill)

    if(not len(skills)):
        raise ValueError("No Maching Skills Found")

    return skills

def add_candidate(tbox : TBox, skill_ids):
    person = tbox.Person()
    candidate_skills = toRegisteredSkills(skill_ids, tbox)
    person.hasSkill = candidate_skills
    return person





# ---------------------------------------------------------------------------
# 6. REASONING ON DEMAND
# ---------------------------------------------------------------------------
def infer(tbox: TBox, candidate: Thing):

    inferred_occupations = []

    with tbox.onto:
        sync_reasoner_hermit(tbox.onto, debug=0)
        for attrib in candidate.INDIRECT_is_a:
            if attrib in tbox.occupations:
                inferred_occupations.append(tbox.occupations[attrib])

    return inferred_occupations


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



def main():
    print(f"model : {MODEL_PATH}")
    print(f"data  : {ESCO_DATA}")
    print(f"store : {ESCO_QUAD}\n")

    load_esco()
    print(f"data loaded: {len(esco_world.graph):,} triples (read-only)\n")
    # load_model() is deliberately NOT called: it is the only thing that
    # writes to the quadstore, and nothing in the pipeline reads it. A
    # PREFIX is textual IRI expansion -- it does not need the TBox loaded.

    # --- step 3: retrieval -------------------------------------------------
    print("\n[3] candidate_occupations(FIXTURE_SKILLS)")
    rows = candidate_occupations(FIXTURE_SKILLS, limit=20)
    names = labels_for([occ for occ, _ in rows])
    print("    shortlist (top 5):")
    for occ, n in rows[:5]:
        print(f"      {n}  {names.get(occ, occ)}")

    # --- step 4: the TBox --------------------------------------------------
    print("\n[4] build_tbox(...)")
    tbox = build_tbox(rows, min_skills=3)
    print(f"    reasoner will see {len(tbox.world.graph):,} triples "
          f"(esco_world has {len(esco_world.graph):,})")

    # --- step 5: the candidate ---------------------------------------------
    print("\n[5] add_candidate(tbox, FIXTURE_SKILLS)")
    person = add_candidate(tbox, FIXTURE_SKILLS)
    print(f"    individual : {person}")
    print(f"    asserted   : {len(person.hasSkill)} skills")

    # map the generated individuals back to readable ESCO labels
    back = {ind: ent for ent, ind in tbox.skills.items()}
    skill_names = labels_for([back[i] for i in person.hasSkill if i in back])
    for ind in person.hasSkill:
        print(f"      - {skill_names.get(back.get(ind), ind)}")

    # --- the guard paths, which the happy case never exercises -------------
    print("\n[5b] guards")
    print("    a skill ESCO knows but the shortlist does not need:")
    add_candidate(tbox, FIXTURE_SKILLS[:2] + [
        "http://data.europa.eu/esco/skill/ccd0a1d9-afda-43d9-b901-96344886e14d"])  # Python
    print("    an IRI that does not exist at all:")
    add_candidate(tbox, FIXTURE_SKILLS[:2] + ["http://data.europa.eu/esco/skill/nope"])
    print("    a profile with nothing usable (expect ValueError):")
    try:
        add_candidate(tbox, ["http://data.europa.eu/esco/skill/nope"])
    except ValueError as exc:
        print(f"      raised: {exc}")

    # --- step 6 ------------------------------------------------------------
    print("\n[6] infer(...)")
    try:
        result = infer(tbox, person)
        print("    inferred:", result)
    except NotImplementedError:
        print("    not written yet -- this is your next step.")
        print("    Expect: assistant clinical psychologist, clinical psychologist,")
        print("            health psychologist, psychotherapist")
    finally:
        # Nothing here was ever on disk, but closing releases the connection
        # and lets the memory go now rather than at GC time -- which matters
        # once you loop over many candidates.
        tbox.world.close()
        print("\n    TBox world closed; nothing was written to disk.")


if __name__ == "__main__":
    main()
