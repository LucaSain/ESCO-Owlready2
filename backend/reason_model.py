"""Run Pellet over the ESCO model ontology (the TBox).

Not over esco.rdf: that dump is SKOS data with 0 owl:Class and ~8M triples,
so a DL reasoner has nothing to derive and OOMs loading it. esco-model.rdf is
the actual ontology -- 41 named classes, 62 object properties, 21 data
properties.

    python reason_model.py
"""
import os
import re
import sys
import tempfile
from pathlib import Path

# Must precede the owlready2 import. owlready2 exports the ontology to
# tempfile.gettempdir() before invoking Java; /tmp here is a 16 GB tmpfs, and
# a large export fills it -> "no space left on device".
_TMP = Path(__file__).parent / "tmp"
_TMP.mkdir(exist_ok=True)
os.environ["TMPDIR"] = str(_TMP)
tempfile.tempdir = str(_TMP)

from owlready2 import World, reasoning, sync_reasoner_pellet  # noqa: E402

# MEGABYTES, not bytes. The original 8*1024*1024 meant -Xmx8388608M, an 8 TB
# heap, which is why the JVM aborted trying to commit 146 GB.
reasoning.JAVA_MEMORY = 4096

MODEL_PATH = Path(os.environ.get("ESCO_MODEL", Path(__file__).parent / "esco-model.rdf"))

IMPORTS_RE = re.compile(r'owl:imports\s+rdf:resource="([^"]+)"')


def stub_imports(world, path):
    """Register each owl:imports target as an already-loaded empty ontology.

    owlready2 resolves imports by downloading them, and ESCO's model imports
    http://purl.org/iso25964/skos-thes, which 404s -- aborting the whole load
    with OwlReadyOntologyParsingError. Ontology.load() returns immediately
    when `loaded` is already True, so pre-registering the IRIs skips fetching.

    Trade-off: axioms from SKOS/SKOS-XL/ADMS are absent, so inferences that
    would depend on them are not drawn. ESCO's own class hierarchy is
    self-contained and classifies fine without them.
    """
    iris = sorted(set(IMPORTS_RE.findall(path.read_text(encoding="utf-8"))))
    for iri in iris:
        # get_ontology() normalises a bare IRI by appending "#", and matches
        # that form against already-registered ontologies.
        stub = world.get_ontology(iri if iri.endswith(("#", "/")) else iri + "#")
        stub.loaded = True
    return iris


def main():
    if not MODEL_PATH.exists():
        sys.exit(
            f"Model ontology not found: {MODEL_PATH}\n"
            "Get it with:\n"
            "  curl -L -o esco-model.rdf https://ec.europa.eu/esco/lod/static/model.rdf"
        )

    # A separate World keeps the reasoner away from the 8M-triple data store.
    world = World()

    for iri in stub_imports(world, MODEL_PATH):
        print(f"stubbed import: {iri}")

    onto = world.get_ontology(MODEL_PATH.as_uri()).load()
    print(f"\nloaded: {onto.base_iri}")
    print(f"classes          : {len(list(onto.classes()))}")
    print(f"object properties: {len(list(onto.object_properties()))}")
    print(f"data properties  : {len(list(onto.data_properties()))}")

    before = {c: set(c.ancestors()) for c in onto.classes()}
    with onto:
        sync_reasoner_pellet(
            infer_property_values=True,
            infer_data_property_values=True,
            debug=0,
        )
    print("\nReasoner: Pellet")

    found = False
    for cls in onto.classes():
        gained = set(cls.ancestors()) - before.get(cls, set())
        if gained:
            found = True
            print(f"  {cls.name}")
            for g in sorted(gained, key=str):
                print(f"      -> subclass of {g}")
    if not found:
        print("  (no new subsumptions -- the stated hierarchy is already complete)")


if __name__ == "__main__":
    main()
