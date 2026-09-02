"""3. Threshold and skillset size

Generated from the notebook of the same name. Runs as a plain script:

    backend/env/bin/python measurements/03_threshold_and_skillset.py

The `# %%` markers are cell separators -- step through them in VS Code,
PyCharm or Spyder if you prefer, or just run the file.

Figures are written to measurements/figures/ rather than shown inline.
"""


# %% [markdown]
# # 3. Threshold and skillset size
#
# Two sweeps, in the order the parameters actually interact:
#
# 1. **Fix a base skillset, sweep `min_skills` from 1 to 10.** How many
#    occupations does the reasoner infer, and what does it cost?
# 2. **Fix `min_skills`, grow the skillset.** Sample skills at random and
#    increase the count, repeating to average out which skills got picked.
#
# This runs the reasoner directly rather than over HTTP, so there is no proxy
# timeout in the way and we can instrument it properly.
#
# > **This notebook is slow, and unevenly so.** A 6-skill optics profile costs
# > 2.9 s at `min_skills=2` and **117 s** at 3. Every call is wrapped in a hard
# > timeout and the results table records what timed out, so a sweep finishes
# > instead of hanging. Read the `timed_out` column before reading the graphs.

# %%
import os, random, sys, time
import matplotlib.pyplot as plt

from common import heading, reason_with_timeout, save, show
import pandas as pd

sys.path.insert(0, os.path.abspath("../backend"))

import esco_store as store
import matching
import reasoning

store.open_store()
matching.skill_index()          # warm the typeahead index
print(f"store: {len(store.default_world.graph):,} triples")
print(f"defaults: MIN_SKILLS={reasoning.DEFAULT_MIN_SKILLS} "
      f"SHORTLIST={reasoning.DEFAULT_SHORTLIST}")

SKILL_NS = reasoning.SKILL_NS
TIMEOUT_S = float(os.environ.get("REASON_TIMEOUT", "150"))
random.seed(20260901)           # reproducible sampling

# %% [markdown]
# ## Running the reasoner with a wall-clock budget
#
# Each call runs in a **subprocess with its own process group**, so a timeout
# can actually kill the work. This is not fussiness: owlready2 spawns HermiT
# as a JVM grandchild, and a thread-based timeout can only stop *waiting* --
# the JVM keeps running and starves every later call.
#
# An early version of this script used a thread and reported `min_skills`
# 5 through 10 as all timing out. Only 5 is genuinely slow: 7 and 10 finish
# in a few seconds. The later "timeouts" were abandoned JVMs from the one
# slow call still consuming CPU. Measurement harnesses can lie.

# %%
def timed_recommend(skill_ids, min_skills, shortlist=None):
    """(seconds, n_inferred, n_shortlist, timed_out)"""
    return reason_with_timeout(
        skill_ids, min_skills,
        shortlist=shortlist or reasoning.DEFAULT_SHORTLIST,
        timeout=TIMEOUT_S)

# %% [markdown]
# ## 3.1 Sweep `min_skills` on a fixed base skillset
#
# The base profile is the six essential skills of *assistant clinical
# psychologist* — a coherent, real profile rather than an arbitrary sample, so
# the sweep isolates the threshold.
#
# The prediction worth testing: as the threshold rises, inferred occupations
# fall (harder to satisfy) while cost rises (more selections to search).

# %%
BASE_LABELS = [
    "assess healthcare users' risk for harm",
    "psychological interventions",
    "comply with quality standards related to healthcare practice",
    "apply psychological intervention strategies",
    "therapy in health care",
    "work with patterns of psychological behaviour",
]

def ids_for(labels):
    out = []
    for lbl in labels:
        hits = matching.search_skills(lbl, limit=1)
        if hits:
            out.append(SKILL_NS + hits[0]["id"])
    return out

base = ids_for(BASE_LABELS)
print(f"base skillset: {len(base)} skills")

rows = []
for th in range(1, 11):
    secs, inferred, shortlist, to = timed_recommend(base, th)
    rows.append({"min_skills": th, "seconds": secs, "inferred": inferred,
                 "shortlist": shortlist, "timed_out": to})
    flag = "  TIMED OUT" if to else ""
    print(f"  min_skills={th:2}  {secs:7.1f}s  inferred={inferred}{flag}")

sweep = pd.DataFrame(rows)
show(sweep)

# %%
fig, (a, b) = plt.subplots(1, 2, figsize=(11, 3.8))

ok = sweep[~sweep.timed_out]
a.plot(ok.min_skills, ok.inferred, marker="o")
a.set_xlabel("min_skills"); a.set_ylabel("occupations inferred")
a.set_title(f"Recall falls as the threshold rises\n({len(base)} skills in the profile)")
a.grid(alpha=.3); a.set_xticks(range(1, 11))

b.plot(ok.min_skills, ok.seconds, marker="s", color="darkorange")
if sweep.timed_out.any():
    t = sweep[sweep.timed_out]
    b.scatter(t.min_skills, t.seconds, marker="x", s=90, color="crimson",
              zorder=3, label=f"timed out (>{TIMEOUT_S:.0f}s)")
    b.legend()
b.set_xlabel("min_skills"); b.set_ylabel("reasoning seconds")
b.set_title("Cost is not monotonic"); b.set_yscale("log")
b.grid(alpha=.3, which="both"); b.set_xticks(range(1, 11))

fig.tight_layout()
save(fig, "03_01")

# %% [markdown]
# Note the threshold cannot exceed the profile size in any useful way: with 6
# skills, `min_skills=7` can never be satisfied, so inferred drops to 0 by
# construction. The interesting range is `1..len(base)`.

# %% [markdown]
# ## 3.2 Grow the skillset at a fixed threshold
#
# Now `min_skills` is held at the deployed default and the profile grows.
# Because *which* skills get sampled matters enormously — a coherent set
# behaves nothing like a scattered one — each size is repeated `TRIALS` times
# with different random draws and we plot the spread, not a single line.
#
# Skills are drawn from those that are essential for at least one occupation;
# sampling the full 14,257 would mostly draw skills no occupation requires,
# which tells us nothing.

# %%
FIXED_TH = reasoning.DEFAULT_MIN_SKILLS
SIZES = [1, 2, 3, 5, 8, 12, 20]
TRIALS = 3

# Only skills that some occupation actually requires.
pool = [str(store.iri(s)) for s, in store.sparql(
    "SELECT DISTINCT ?s { ?o a esco:Occupation ; esco:relatedEssentialSkill ?s }")]
print(f"sampling pool: {len(pool):,} skills that are essential somewhere")

rows = []
for n in SIZES:
    for trial in range(TRIALS):
        ids = random.sample(pool, n)
        secs, inferred, shortlist, to = timed_recommend(ids, FIXED_TH)
        rows.append({"n_skills": n, "trial": trial, "seconds": secs,
                     "inferred": inferred, "shortlist": shortlist, "timed_out": to})
    got = [r for r in rows if r["n_skills"] == n]
    print(f"  n={n:2}  median {pd.Series([g['seconds'] for g in got]).median():6.1f}s  "
          f"inferred {[g['inferred'] for g in got]}")

grow = pd.DataFrame(rows)
show(grow.groupby("n_skills").agg(
    median_s=("seconds", "median"), max_s=("seconds", "max"),
    median_inferred=("inferred", "median"), timeouts=("timed_out", "sum")).round(1))

# %%
fig, (a, b) = plt.subplots(1, 2, figsize=(11, 3.8))

g = grow[~grow.timed_out]
a.scatter(g.n_skills, g.inferred, alpha=.7)
med = g.groupby("n_skills").inferred.median()
a.plot(med.index, med.values, color="crimson", label="median")
a.set_xlabel("skills in the profile"); a.set_ylabel("occupations inferred")
a.set_title(f"Recall vs profile size (min_skills={FIXED_TH})")
a.legend(); a.grid(alpha=.3)

a2 = b
a2.scatter(g.n_skills, g.seconds, alpha=.7, color="darkorange")
med2 = g.groupby("n_skills").seconds.median()
a2.plot(med2.index, med2.values, color="crimson", label="median")
if grow.timed_out.any():
    t = grow[grow.timed_out]
    a2.scatter(t.n_skills, t.seconds, marker="x", s=90, color="crimson",
               zorder=3, label="timed out")
a2.set_xlabel("skills in the profile"); a2.set_ylabel("reasoning seconds")
a2.set_title("Cost vs profile size"); a2.set_yscale("log")
a2.legend(); a2.grid(alpha=.3, which="both")

fig.tight_layout()
save(fig, "03_02")

# %% [markdown]
# ## 3.3 The two parameters together
#
# A coarse grid, to see whether the threshold interacts with profile size or
# merely adds to it. Kept small on purpose — this is the most expensive cell in
# the notebook.

# %%
GRID_SIZES = [3, 6, 10]
GRID_TH = [1, 2, 3, 4]

cells = []
for n in GRID_SIZES:
    ids = random.sample(pool, n)      # one draw per row, so rows are comparable
    for th in GRID_TH:
        if th > n:
            cells.append({"n_skills": n, "min_skills": th, "seconds": float("nan"),
                          "inferred": 0, "timed_out": False, "impossible": True})
            continue
        secs, inferred, _, to = timed_recommend(ids, th)
        cells.append({"n_skills": n, "min_skills": th, "seconds": secs,
                      "inferred": inferred, "timed_out": to, "impossible": False})
        print(f"  n={n:2} th={th}  {secs:7.1f}s  inferred={inferred}"
              f"{'  TIMED OUT' if to else ''}")

grid = pd.DataFrame(cells)
pivot_t = grid.pivot(index="n_skills", columns="min_skills", values="seconds")
pivot_i = grid.pivot(index="n_skills", columns="min_skills", values="inferred")
show(pivot_t.round(1))
show(pivot_i)

# %%
fig, axes = plt.subplots(1, 2, figsize=(11, 3.6))
for ax, piv, title, fmt in (
    (axes[0], pivot_t, "reasoning seconds", "{:.0f}"),
    (axes[1], pivot_i, "occupations inferred", "{:.0f}"),
):
    im = ax.imshow(piv.values, cmap="viridis", aspect="auto")
    ax.set_xticks(range(len(piv.columns))); ax.set_xticklabels(piv.columns)
    ax.set_yticks(range(len(piv.index))); ax.set_yticklabels(piv.index)
    ax.set_xlabel("min_skills"); ax.set_ylabel("skills in profile")
    ax.set_title(title)
    for i in range(piv.shape[0]):
        for j in range(piv.shape[1]):
            v = piv.values[i, j]
            ax.text(j, i, "-" if pd.isna(v) else fmt.format(v),
                    ha="center", va="center", color="w", fontsize=8)
    fig.colorbar(im, ax=ax, shrink=.85)
fig.tight_layout()
save(fig, "03_03")

# %% [markdown]
# ## What to take from this
#
# Fill in from your run, but the claims worth checking:
#
# - **Recall falls monotonically with `min_skills`** — that part should be
#   clean, and it is the defensible reason to state a threshold at all.
# - **Cost does not.** If the seconds plot is non-monotonic or spiky, that is
#   the finding: the threshold changes the *shape* of the tableau search, not
#   just its size, so you cannot budget by counting anything cheap beforehand.
# - **Variance across trials at the same size** is the argument that "profile
#   size" is the wrong predictor. If three random 8-skill profiles differ by an
#   order of magnitude in cost, no size-based cap will save you — only a
#   timeout will.
# - **`min_skills > len(profile)` is unsatisfiable by construction.** Worth
#   stating explicitly so a zero is not misread as a modelling failure.
