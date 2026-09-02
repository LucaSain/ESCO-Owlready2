"""One reasoning call, in its own process group, printing JSON.

Run as a subprocess by common.reason_with_timeout so a timeout can actually
KILL the work -- including the JVM that owlready2 spawns as a grandchild.
A thread-based timeout can only abandon it, and abandoned JVMs then starve
every later call in the sweep.

    python _worker.py '<json-list-of-skill-iris>' <min_skills> <shortlist>
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))

import esco_store as store   # noqa: E402
import reasoning             # noqa: E402

store.open_store()
skill_ids = json.loads(sys.argv[1])
min_skills = int(sys.argv[2])
shortlist = int(sys.argv[3])

result = reasoning.recommend(skill_ids, shortlist=shortlist, min_skills=min_skills)
print("__RESULT__" + json.dumps({
    "seconds": result["seconds"],
    "inferred": len(result["occupations"]),
    "shortlist": len(result["shortlist"]),
}))
