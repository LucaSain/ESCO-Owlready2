from fastapi import FastAPI
import re
import sys
from pathlib import Path
from owlready2 import (
    World, get_ontology, sync_reasoner_pellet, sync_reasoner_hermit,
    default_world, Thing, reasoning
)
from contextlib import asynccontextmanager
from pydantic import BaseModel, Field

import esco_store as store
import matching

# The TBox gets its own World. default_world is bound to the 7.9M-triple data
# quadstore, and loading the model there would write the schema into it.
MODEL_WORLD = World()


@asynccontextmanager
async def lifespan(app: FastAPI):

    print()

    store.open_store()
    print(f"data store: {len(default_world.graph):,} triples")

    reasoning.JAVA_MEMORY = 4096
    onto = load("esco-model.rdf")
    before, after = reason(onto)
    show_inferences(before, after)
    yield
    onto.destroy()  # Ontology has no .clear()

app = FastAPI(lifespan=lifespan)

IMPORTS_RE = re.compile(r'owl:imports\s+rdf:resource="([^"]+)"')


def stub_imports(p: Path):
    """Register owl:imports targets as already-loaded empty ontologies.

    owlready2 resolves imports by downloading them, and the ESCO model
    imports http://purl.org/iso25964/skos-thes, which 404s -- that aborts the
    whole load with OwlReadyOntologyParsingError. Ontology.load() returns
    early when `loaded` is already True, so this skips the fetch.

    Trade-off: axioms from those vocabularies are absent, so inferences
    depending on them are not drawn. ESCO's own hierarchy is self-contained.
    """
    for iri in sorted(set(IMPORTS_RE.findall(p.read_text(encoding="utf-8")))):
        # get_ontology() appends "#" to a bare IRI and matches that form
        # against ontologies already registered in the world.
        target = iri if iri.endswith(("#", "/")) else iri + "#"
        MODEL_WORLD.get_ontology(target).loaded = True
        print(f"stubbed import: {iri}")


def load(path: str):
    p = Path(path).expanduser().resolve()
    if not p.exists():
        sys.exit(f"File not found: {p}")
    stub_imports(p)
    onto = MODEL_WORLD.get_ontology(p.as_uri()).load()
    print(f"Loaded: {onto.base_iri}")
    print(f"classes          : {len(list(onto.classes()))}")
    print(f"object properties: {len(list(onto.object_properties()))}")
    print(f"data properties  : {len(list(onto.data_properties()))}")
    print(f"individuals      : {len(list(onto.individuals()))}")
    return onto

def snapshot(onto):
    return {
        e.name: {c.name for c in e.INDIRECT_is_a if hasattr(c, "name")}
        for e in list(onto.classes()) + list(onto.individuals())
        if hasattr(e, "INDIRECT_is_a")
    }


def reason(onto):
    before = snapshot(onto)

    try:
        with onto:
            # Passing `onto` is required, not cosmetic: with no argument these
            # default to owlready2.default_world, which is now the 7.9M-triple
            # data store -- the exact thing that OOM'd the JVM originally.
            sync_reasoner_pellet(
                onto,
                infer_property_values=True,
                infer_data_property_values=True,
                debug=0,
            )
        print("\nReasoner: Pellet")
    except Exception as e_pellet:
        print("\nPellet did not start, falling back to Hermit.")
        try:
            with onto:
                sync_reasoner_hermit(onto, infer_property_values=True, debug=0)
            print("Reasoner: HermiT")
        except Exception as e_hermit:
            sys.exit("Both reasoners failed. \n"
                     f"  Pellet: {str(e_pellet)[:180]}\n"
                     f"  HermiT: {str(e_hermit)[:180]}")

    after = snapshot(onto)
    return before, after


def show_inferences(before, after):
    """Print only what the reasoner ADDED. """
    found = False
    for name, classes_after in sorted(after.items()):
        gained = classes_after - before.get(name, set())
        if gained:
            found = True
            print(f"  {name}")
            for c in sorted(gained):
                print(f"      -> is also a  {c}")
    if not found:
        print("  (nothing new - check that your defined classes use "
              "'Equivalent To', not 'SubClass Of')")



def members_of(onto, class_name):
    """Every individual the reasoner considers a member of class_name."""
    cls = onto[class_name]
    if cls is None:
        return []
    return [i for i in onto.individuals() if cls in i.INDIRECT_is_a]


@app.get("/")
async def root():
    return {"message": "Hello World"}


@app.get("/skills")
async def skills(q: str, lang: str = "en", limit: int = 20):
    """Find skill ids by label, to build a profile for /match."""
    return matching.search_skills(q, lang, limit)


class Profile(BaseModel):
    skill_ids: list[str] = Field(..., description="ESCO skill UUIDs, from /skills")
    lang: str = "en"
    limit: int = Field(10, ge=1, le=100)
    min_essential: int = Field(1, ge=0, description="ignore occupations requiring fewer skills")
    sort: str = Field("score", pattern="^(score|matches)$")
    include_gaps: bool = True


@app.post("/match")
async def match(profile: Profile):
    """Rank occupations against a set of skills.

    Plain SPARQL aggregation over the data store -- no OWL reasoner involved,
    because ESCO's data carries no class axioms one could exploit.
    """
    return matching.match(
        profile.skill_ids,
        lang=profile.lang,
        limit=profile.limit,
        min_essential=profile.min_essential,
        include_gaps=profile.include_gaps,
        sort=profile.sort,
    )