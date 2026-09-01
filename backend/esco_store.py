"""Shared access to the ESCO quadstore.

ESCO is a SKOS thesaurus, not an OWL ontology: the dump contains zero
owl:Class / owl:ObjectProperty / owl:NamedIndividual declarations. Everything
is reached through SPARQL over rdf:type instead of onto.classes().
"""
import os
from pathlib import Path

from owlready2 import default_world

BACKEND_DIR = Path(__file__).parent
RDF_PATH = Path(os.environ.get("ESCO_RDF", BACKEND_DIR / "esco.rdf"))
STORE_PATH = Path(os.environ.get("ESCO_STORE", BACKEND_DIR / "esco.sqlite3"))

# The dump has no owl:Ontology header, so we name the graph ourselves rather
# than letting owlready2 derive a file:// base IRI from the path.
BASE_IRI = "http://data.europa.eu/esco/"

PREFIXES = """
PREFIX rdf:     <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs:    <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos:    <http://www.w3.org/2004/02/skos/core#>
PREFIX skosxl:  <http://www.w3.org/2008/05/skos-xl#>
PREFIX esco:    <http://data.europa.eu/esco/model#>
PREFIX dct:     <http://purl.org/dc/terms/>
PREFIX adms:    <http://www.w3.org/ns/adms#>
"""

_opened = False


def open_store(exclusive: bool = False, read_only: bool = True):
    """Attach default_world to the on-disk quadstore.

    The store must never be in-memory: the full dump is ~7.9M triples and the
    default in-memory backend would need far more RAM than this machine has.

    read_only opens sqlite with mode=ro. Without it, owlready2 runs ANALYZE
    (a write) on open, so a second process -- a reloading `fastapi dev`, or a
    second uvicorn worker -- fails with "database is locked". The API only
    reads; ingest.py sets its own writable backend.
    """
    global _opened
    if _opened:
        return default_world
    if not STORE_PATH.exists():
        raise FileNotFoundError(
            f"Quadstore not found: {STORE_PATH}\n"
            f"The 1.2 GB store is not shipped in the container image; it has "
            f"to be put on the mounted volume once.\n"
            f"  local dev  : python ingest.py   (parses ESCO_RDF, ~30s)\n"
            f"  container  : copy an existing esco.sqlite3 onto the volume "
            f"backing {STORE_PATH.parent}, e.g.\n"
            f"               docker run --rm -v <volume>:/data -v $PWD:/src "
            f"alpine cp /src/esco.sqlite3 /data/\n"
            f"Set ESCO_STORE to change where it is looked for."
        )
    default_world.set_backend(
        filename=str(STORE_PATH), exclusive=exclusive, read_only=read_only
    )
    _opened = True
    return default_world


def sparql(query: str, params=None):
    """Run a SPARQL query with the ESCO prefixes bound.

    error_on_undefined_entities=False is required: predicates such as
    skos:prefLabel are legal but simply unused by ESCO, and owlready2 raises
    on any IRI absent from the store rather than returning no rows.
    """
    # `params or ()` matters: owlready2 iterates this value, so an explicit
    # None raises TypeError where the default empty tuple works.
    return default_world.sparql(
        PREFIXES + query, params or (), error_on_undefined_entities=False
    )


def iri(value):
    """Normalise a SPARQL result cell to a plain string IRI."""
    return getattr(value, "iri", value)


def uuid_of(value):
    """Last path segment of an ESCO IRI, used as the public id."""
    return str(iri(value)).rsplit("/", 1)[-1]


def type_counts() -> dict:
    """Population of the store by rdf:type -- the meaningful replacement for
    len(onto.classes()), which is legitimately 0 for this dataset."""
    out = {}
    for t, n in sparql("SELECT ?t (COUNT(?s) AS ?n) { ?s a ?t } GROUP BY ?t ORDER BY DESC(?n)"):
        out[str(iri(t))] = n
    return out


def labels_for(entities, lang: str = "en") -> dict:
    """{entity: preferred label} for a handful of entities.

    ESCO uses SKOS-XL, so label text is not on the concept -- it hangs off a
    skosxl:Label node via skosxl:prefLabel, then skosxl:literalForm.

    The IN filter is load-bearing. Without it owlready2 plans this from the
    1.1M skosxl:Label triples and the query takes ~40s; constrained to the
    entities you already hold it is well under a second.
    """
    if not entities:
        return {}
    return {
        entity: str(form)
        for entity, form in sparql(
            """SELECT ?e ?form {
                 ?e skosxl:prefLabel ?lb . ?lb skosxl:literalForm ?form .
                 FILTER(?e IN ??1 && LANG(?form) = ??2)
               }""",
            [list(entities), lang],
        )
    }
