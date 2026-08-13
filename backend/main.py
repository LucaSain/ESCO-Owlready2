from fastapi import FastAPI
import sys
from pathlib import Path
from owlready2 import (
    get_ontology, sync_reasoner_pellet, sync_reasoner_hermit,
    default_world, Thing, reasoning
)
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    
    print()
    reasoning.JAVA_MEMORY = 8*1024*1024
    onto = load("esco.rdf")
    before,after = reason(onto)
    yield
    onto.clear()

app = FastAPI(lifespan=lifespan)

def load(path: str):
    p = Path(path).expanduser().resolve()
    if not p.exists():
        sys.exit(f"File not found: {p}")
    onto = get_ontology(p.as_uri()).load()
    print(f"Loaded: {onto.base_iri}")
    print(f"classes          : {len(list(onto.classes()))}")
    print(f"object properties: {len(list(onto.object_properties()))}")
    print(f"data properties  : {len(list(onto.data_properties()))}")
    print(f"individuals      : {len(list(onto.individuals()))}")
    return onto

def snapshot(onto):
    return {
        ind.name: {c.name for c in ind.INDIRECT_is_a if hasattr(c, "name")}
        for ind in onto.individuals()
    }


def reason(onto):
    before = snapshot(onto)

    try:
        with onto:
            sync_reasoner_pellet(
                infer_property_values=True,
                infer_data_property_values=True,
                debug=0,
            )
        print("\nReasoner: Pellet")
    except Exception as e_pellet:
        print("\nPellet did not start, falling back to Hermit.")
        try:
            with onto:
                sync_reasoner_hermit(infer_property_values=True, debug=0)
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