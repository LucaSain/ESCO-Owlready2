"""One-time build of the ESCO quadstore.

Parsing 1.1 GB of RDF/XML takes minutes, so it must not happen in the FastAPI
lifespan -- every reload would redo it. Run this once:

    python ingest.py

It writes esco.sqlite3 next to esco.rdf; main.py then just opens that file.
"""
import sys
import time

from owlready2 import default_world, get_ontology

import esco_store as store


def main():
    if not store.RDF_PATH.exists():
        sys.exit(f"RDF not found: {store.RDF_PATH}")

    if store.STORE_PATH.exists():
        sys.exit(
            f"Quadstore already exists: {store.STORE_PATH}\n"
            f"Delete it first to rebuild."
        )

    size_gb = store.RDF_PATH.stat().st_size / 1e9
    print(f"Loading {store.RDF_PATH} ({size_gb:.2f} GB) -> {store.STORE_PATH}")
    print("This takes several minutes; the store will be a few GB on disk.")

    # exclusive=True keeps sqlite unshared for the duration of the bulk load,
    # which is markedly faster than the shared-access mode used at serve time.
    default_world.set_backend(filename=str(store.STORE_PATH), exclusive=True)

    onto = get_ontology(store.BASE_IRI)
    t0 = time.time()
    with open(store.RDF_PATH, "rb") as f:
        onto.load(fileobj=f, reload=True)
    default_world.save()
    print(f"Parsed in {time.time() - t0:.0f}s")

    print(f"triples: {len(default_world.graph):,}")
    print(f"store  : {store.STORE_PATH.stat().st_size / 1e9:.2f} GB")

    # These are 0 by design -- ESCO declares no OWL entities. Printed so the
    # contrast with the rdf:type census below is obvious.
    print(f"\nowl:Class          : {len(list(onto.classes()))}")
    print(f"owl:ObjectProperty : {len(list(onto.object_properties()))}")
    print(f"owl:NamedIndividual: {len(list(onto.individuals()))}")

    print("\nActual population by rdf:type:")
    for t, n in store.type_counts().items():
        print(f"  {n:>9,}  {t}")


if __name__ == "__main__":
    main()
