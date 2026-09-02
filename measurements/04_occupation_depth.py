"""4. Measuring the "depth" of an occupation

Generated from the notebook of the same name. Runs as a plain script:

    backend/env/bin/python measurements/04_occupation_depth.py

The `# %%` markers are cell separators -- step through them in VS Code,
PyCharm or Spyder if you prefer, or just run the file.

Figures are written to measurements/figures/ rather than shown inline.
"""


# %% [markdown]
# # 4. Measuring the "depth" of an occupation
#
# The matcher uses two relations, `relatedEssentialSkill` and
# `relatedOptionalSkill`. ESCO carries considerably more, and some of it can be
# turned into a defensible measure of how *specialised* a job is.
#
# "Depth" and "expertise" have no definition in ESCO, so this notebook does not
# pretend to measure them directly. Instead it builds four proxies that are
# each individually defensible, looks at whether they agree, and only then
# combines them. Where a proxy is weaker than its name suggests, that is said
# plainly rather than hidden in a composite score.
#
# **The relations available** (counts are triples, on 3,046 occupations and
# 14,257 skills):
#
# | relation | count | used here |
# |---|---|---|
# | `esco:relatedEssentialSkill` | 67,600 | yes — signals A, C |
# | `esco:relatedOptionalSkill` | 58,451 | yes — signal C |
# | `esco:isEssentialSkillFor` | 67,789 | yes — signal A (the inverse) |
# | `skos:broaderTransitive` (skills) | 81,992 | yes — signal B |
# | `skos:inScheme` | — | yes — signal D |
# | `skos:broaderTransitive` (occupations) | 13,622 | yes — ISCO position |
# | `esco:hasAssociation` | 125,504 | no — reified n-ary links, adds no depth signal |
# | `esco:hasNACECode` | 4,564 | no — industry, orthogonal to depth |

# %%
import os, sys, math
import matplotlib.pyplot as plt

from common import heading, save, show
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath("../backend"))
import esco_store as store
from esco_store import sparql, iri, labels_for, uuid_of

store.open_store()
print(f"store: {len(store.default_world.graph):,} triples")

# %% [markdown]
# ## 4.0 The raw bipartite graph
#
# One query for every occupation-to-skill edge, essential and optional, with no
# label joins — joining labels here would make owlready2 plan from the 1.1M
# `skosxl:Label` triples and take ~40 s instead of well under one.

# %%
edges = []
for rel, essential in (("relatedEssentialSkill", True), ("relatedOptionalSkill", False)):
    for occ, skill in sparql(
        f"SELECT ?o ?s {{ ?o a esco:Occupation ; esco:{rel} ?s }}"):
        edges.append((uuid_of(occ), uuid_of(skill), essential))

E = pd.DataFrame(edges, columns=["occ", "skill", "essential"])
print(f"{len(E):,} edges  |  {E.occ.nunique():,} occupations  |  {E.skill.nunique():,} skills")
print(f"essential: {E.essential.sum():,}   optional: {(~E.essential).sum():,}")

# %% [markdown]
# ## Signal A — skill rarity (how many jobs need this skill)
#
# The strongest and simplest signal. A skill required by 261 occupations
# ("manage staff") says almost nothing about a person; one required by a single
# occupation ("green logistics") is diagnostic.
#
# This is textbook inverse document frequency, borrowed from information
# retrieval, where occupations are the documents:
#
# $$\mathrm{idf}(s) = \log \frac{N_{\text{occupations}}}{n_s}$$
#
# An occupation's score is the mean idf of its **essential** skills — optional
# ones are excluded here because they say less about what the job *is*.

# %%
N_OCC = E.occ.nunique()
reuse = E[E.essential].groupby("skill").occ.nunique().rename("n_occupations")
idf = np.log(N_OCC / reuse).rename("idf")

print(f"reuse: min {reuse.min()}  median {reuse.median():.0f}  max {reuse.max()}")
print(f"idf  : {idf.min():.2f} .. {idf.max():.2f}")

ess = E[E.essential].merge(idf, left_on="skill", right_index=True)
sigA = ess.groupby("occ").idf.mean().rename("mean_idf")
show(sigA.describe().round(3).to_frame().T)

# %% [markdown]
# ## Signal B — position in the skills taxonomy
#
# ESCO's skills form a hierarchy via `skos:broader`. A skill far from the root
# is a narrower concept, so counting ancestors is a specificity proxy.
#
# **Caveat that matters:** the hierarchy is a DAG, not a tree — a skill can have
# several parents, and `broaderTransitive` counts ancestors along *every* path.
# "clean vehicle engine" has 39 ancestors, which reflects multiple inheritance
# rather than 39 levels of nesting. So this measures *how richly classified* a
# skill is, which correlates with specificity but is not literally depth. Named
# `n_ancestors` rather than `depth` for that reason.

# %%
anc = {uuid_of(s): d for s, d in sparql(
    "SELECT ?s (COUNT(?a) AS ?d) { ?s a esco:Skill ; skos:broaderTransitive ?a } GROUP BY ?s")}
ancestors = pd.Series(anc, name="n_ancestors")
print(f"{len(ancestors):,} skills classified; "
      f"min {ancestors.min()} median {ancestors.median():.0f} max {ancestors.max()}")

sigB = (E[E.essential]
        .merge(ancestors, left_on="skill", right_index=True)
        .groupby("occ").n_ancestors.mean().rename("mean_ancestors"))
show(sigB.describe().round(2).to_frame().T)

# %% [markdown]
# ## Signal C — how much of the job is mandatory
#
# $$\text{essential share} = \frac{|\text{essential}|}{|\text{essential}| + |\text{optional}|}$$
#
# A job defined mostly by *required* skills is more tightly specified than one
# that is mostly optional extras. This is a measure of how constrained the role
# is, which is related to but distinct from how specialised its skills are —
# worth keeping separate so we can check whether they actually agree.

# %%
counts = E.groupby(["occ", "essential"]).size().unstack(fill_value=0)
counts.columns = ["optional", "essential"] if False in counts.columns else counts.columns
counts = counts.rename(columns={False: "optional", True: "essential"})
counts["total"] = counts.essential + counts.optional
sigC = (counts.essential / counts.total).rename("essential_share")

show(counts.describe().round(1))
print(f"essential share: median {sigC.median():.2f}")

# %% [markdown]
# ## Signal D — transversal load
#
# ESCO marks some skills as *transversal*: generic capabilities that carry
# across occupations. A job whose requirements lean transversal is broad; one
# that leans on domain-specific knowledge is deep.
#
# **Honest limitation, worse than it sounds:** only 127 skills sit in the
# transversal-groups scheme, and in this dump exactly **1 occupation of 3,039**
# has a transversal skill among its essential ones. The signal is empty.
# Computed and shown anyway, because a proxy that turns out to be useless is
# worth demonstrating rather than quietly dropping.

# %%
TRANSVERSAL = "http://data.europa.eu/esco/concept-scheme/skill-transversal-groups"
tv = {uuid_of(s) for s, in sparql(
    "SELECT DISTINCT ?s { ?s a esco:Skill ; skos:inScheme ??1 }", [store.default_world[TRANSVERSAL]])}
print(f"{len(tv)} transversal skills")

ess_only = E[E.essential].copy()
ess_only["is_tv"] = ess_only.skill.isin(tv)
sigD = ess_only.groupby("occ").is_tv.mean().rename("transversal_share")
print(f"occupations with any transversal essential skill: "
      f"{(sigD > 0).sum()} of {len(sigD)}  ({(sigD > 0).mean()*100:.1f}%)")

# %% [markdown]
# ## 4.1 Do the signals agree?
#
# Before combining anything, check whether these measure the same thing. Highly
# correlated signals add no information; uncorrelated ones mean the composite
# is averaging away real distinctions.

# %%
occ_labels = {}
feat = pd.concat([sigA, sigB, sigC, sigD, counts.essential.rename("n_essential")],
                 axis=1).dropna(subset=["mean_idf"])
print(f"{len(feat):,} occupations with a full feature row")

corr = feat[["mean_idf", "mean_ancestors", "essential_share",
             "transversal_share", "n_essential"]].corr(method="spearman")
show(corr.round(2))

fig, ax = plt.subplots(figsize=(5.4, 4.4))
im = ax.imshow(corr.values, cmap="RdBu_r", vmin=-1, vmax=1)
ax.set_xticks(range(len(corr))); ax.set_xticklabels(corr.columns, rotation=45, ha="right", fontsize=8)
ax.set_yticks(range(len(corr))); ax.set_yticklabels(corr.index, fontsize=8)
for i in range(len(corr)):
    for j in range(len(corr)):
        ax.text(j, i, f"{corr.values[i, j]:.2f}", ha="center", va="center", fontsize=8)
ax.set_title("Spearman correlation between signals")
fig.colorbar(im, ax=ax, shrink=.8); fig.tight_layout()
save(fig, "04_01")

# %%
fig, axes = plt.subplots(1, 4, figsize=(13, 3))
for ax, col, title in zip(axes,
        ["mean_idf", "mean_ancestors", "essential_share", "transversal_share"],
        ["A: mean skill idf", "B: mean ancestors", "C: essential share", "D: transversal share"]):
    ax.hist(feat[col].dropna(), bins=40, color="#4a6fa5")
    ax.set_title(title, fontsize=9); ax.grid(alpha=.3)
fig.tight_layout()
save(fig, "04_02")

# %% [markdown]
# ## 4.2 A composite depth index
#
# Each signal is converted to a percentile rank, so scales and skew do not
# matter, then averaged with explicit weights. Weights are a *judgement*, not a
# result — they are stated here so a reader can disagree with them.
#
# Signal A carries the most weight because rarity felt like the least
# assumption-laden of the four. **Section 4.3 tests that belief against ISCO
# and it does not survive** — read on before using this index for anything.

# %%
WEIGHTS = {"mean_idf": 0.45, "mean_ancestors": 0.30, "essential_share": 0.20,
           "transversal_share": -0.05}   # negative: transversal load means breadth

pct = feat[list(WEIGHTS)].rank(pct=True)
feat["depth_index"] = sum(pct[c] * w for c, w in WEIGHTS.items())
feat["depth_index"] = (feat.depth_index - feat.depth_index.min()) / \
                      (feat.depth_index.max() - feat.depth_index.min())

top = feat.nlargest(12, "depth_index")
bottom = feat.nsmallest(12, "depth_index")
names = labels_for([store.default_world[
    "http://data.europa.eu/esco/occupation/" + o] for o in list(top.index) + list(bottom.index)])
lookup = {uuid_of(k): v for k, v in names.items()}

def named_table(frame, title):
    """Not called `show` -- that name belongs to common.show, and shadowing it
    here made this function call itself."""
    out = frame.copy()
    out.insert(0, "occupation", [lookup.get(i, i[:8]) for i in out.index])
    heading(title)
    show(out[["occupation", "depth_index", "mean_idf",
              "mean_ancestors", "essential_share", "n_essential"]].round(3))

named_table(top, "DEEPEST / most specialised")
named_table(bottom, "SHALLOWEST / most general")

# %%
fig, (a, b) = plt.subplots(1, 2, figsize=(12, 4.4))

t = top.iloc[::-1]
a.barh([lookup.get(i, i[:8])[:36] for i in t.index], t.depth_index, color="#2b6b4f")
a.set_xlabel("depth index"); a.set_title("Most specialised occupations")
a.grid(alpha=.3, axis="x"); a.tick_params(labelsize=8)

bo = bottom.iloc[::-1]
b.barh([lookup.get(i, i[:8])[:36] for i in bo.index], bo.depth_index, color="#8a5a3b")
b.set_xlabel("depth index"); b.set_title("Most general occupations")
b.grid(alpha=.3, axis="x"); b.tick_params(labelsize=8)

fig.tight_layout()
save(fig, "04_03")

# %%
fig, (a, b) = plt.subplots(1, 2, figsize=(11, 4))

sc = a.scatter(feat.n_essential, feat.mean_idf, c=feat.depth_index,
               cmap="viridis", s=12, alpha=.7)
a.set_xlabel("number of essential skills"); a.set_ylabel("mean skill idf")
a.set_title("Are big jobs deep jobs?"); a.grid(alpha=.3)
fig.colorbar(sc, ax=a, label="depth index", shrink=.85)

a2 = b
a2.scatter(feat.mean_ancestors, feat.mean_idf, s=12, alpha=.6, color="#4a6fa5")
a2.set_xlabel("mean ancestors (signal B)"); a2.set_ylabel("mean idf (signal A)")
a2.set_title("Do rarity and classification agree?"); a2.grid(alpha=.3)

fig.tight_layout()
print("If the right-hand cloud is diffuse, A and B are measuring different things")
print("and averaging them into one index is destroying information.")
save(fig, "04_04")

# %% [markdown]
# ## 4.3 Sanity check against the ISCO hierarchy
#
# An independent check: ESCO places occupations under ISCO skill levels, and
# ISCO major group 1–3 are managers/professionals/technicians while 9 is
# elementary occupations. If the depth index is measuring anything real, it
# should trend downward across those groups — and crucially, **nothing in the
# index was derived from ISCO**, so agreement is evidence rather than
# circularity.

# %%
isco = {}
for occ, anc in sparql(
    "SELECT ?o ?a { ?o a esco:Occupation ; skos:broaderTransitive ?a }"):
    a = str(iri(anc))
    if "/isco/C" in a:
        code = a.rsplit("/C", 1)[-1]
        if len(code) == 1:                 # major group
            isco[uuid_of(occ)] = code

feat["isco_major"] = pd.Series(isco)
grp = feat.dropna(subset=["isco_major"]).groupby("isco_major")
print(f"{feat.isco_major.notna().sum():,} occupations mapped to an ISCO major group")
show(grp.depth_index.agg(["count", "median"]).round(3))

fig, ax = plt.subplots(figsize=(7.5, 3.8))
keys = sorted(grp.groups)
ax.boxplot([grp.get_group(k).depth_index for k in keys], tick_labels=keys)
ax.set_xlabel("ISCO major group (1 = managers … 9 = elementary)")
ax.set_ylabel("depth index"); ax.set_title("Depth index vs ISCO major group")
ax.grid(alpha=.3); fig.tight_layout()
save(fig, "04_05")

# %% [markdown]
# ## 4.4 Verdict: the index fails, and the simplest signal wins
#
# Measured on this dump (ISCO 1 = managers … 9 = elementary, so a **negative**
# correlation means the measure tracks expertise):
#
# | measure | Spearman vs ISCO major group | reading |
# |---|---|---|
# | `n_essential` — just count the skills | **-0.357** | strongest, correctly signed |
# | `mean_ancestors` (signal B) | -0.133 | weak, correct direction |
# | `depth_index` (the composite) | **+0.045** | no relationship at all |
# | `mean_idf` (signal A) | **+0.193** | **wrong direction** |
#
# Three things follow, and none of them is what I expected when building this.
#
# **Skill rarity measures niche-ness, not expertise.** `mean_idf` correlates
# *positively* with ISCO group number, meaning rare skills cluster in
# *lower*-skilled occupations. It is easy to see why once stated: a pilates
# teacher or a printmaker has a handful of skills nobody else uses, while an
# industrial engineer has many skills shared across all of engineering. Rarity
# of vocabulary is not depth of expertise. The "deepest" list in 4.2 —
# printmaker, fitness instructor, pilates teacher — is the giveaway, and it
# should have been read as a failure rather than a curiosity.
#
# **The composite is worse than its parts.** At +0.045 it is indistinguishable
# from noise. Section 4.1 predicted this: the signals are mutually uncorrelated
# (all |ρ| ≤ 0.15), so averaging them cancels out whatever information each
# carried, and the negatively-signed dominant component actively fights the
# others. Uncorrelated proxies are not evidence of complementarity — they can
# just as easily mean only one of them is measuring anything.
#
# **The best predictor is a count.** How many essential skills an occupation
# has, with no hierarchy, no scheme membership and no weighting judgement,
# correlates -0.357 with ISCO — better than every construct built on top of it.
# That is a real if deflating result, and it is the one to report.
#
# ### If you want to take this further
#
# The honest next step is to stop guessing at a definition and use ISCO's own
# **skill level** as ground truth: fit `n_essential`, `mean_ancestors` and the
# rest against it and see which combination actually predicts. That turns
# "define depth" into a supervised question with an answer, instead of a
# composite whose weights nobody can defend.
#
# Worth keeping separate from the matcher, though. Weighting `shared_skills` by
# idf was the obvious application — and given that idf points the wrong way for
# expertise, it would need testing on ranking quality directly rather than
# being assumed to help.
