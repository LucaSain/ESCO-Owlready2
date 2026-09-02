"""2. Backend performance

Generated from the notebook of the same name. Runs as a plain script:

    backend/env/bin/python measurements/02_backend_performance.py

The `# %%` markers are cell separators -- step through them in VS Code,
PyCharm or Spyder if you prefer, or just run the file.

Figures are written to measurements/figures/ rather than shown inline.
"""


# %% [markdown]
# # 2. Backend performance
#
# Two endpoints with wildly different cost profiles:
#
# | endpoint | what it does | expected |
# |---|---|---|
# | `GET /skills` | scans an in-memory index of 14,257 labels | ~1 ms |
# | `POST /match` | generates an OWL TBox and runs HermiT | seconds |
#
# So they need separate treatment. Measuring them together would just show
# that reasoning dominates, which we already know.
#
# Set `API_URL` to point at the deployed API, or leave the default to hit a
# local backend. Measuring the deployed one folds in Cloudflare and network
# RTT; measuring locally isolates the reasoner. Both are useful — the gap
# between them *is* the network cost.

# %%
import json, os, statistics, time, urllib.parse, urllib.request, urllib.error
import matplotlib.pyplot as plt

from common import heading, save, show
import pandas as pd

API = os.environ.get("API_URL", "http://localhost:8000")
print("target:", API)

def call(path, payload=None, timeout=300):
    url = f"{API}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"} if data else {},
        method="POST" if data else "GET")
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = json.load(r)
    return (time.perf_counter() - t0) * 1000, body

ms, root = call("/")
print(f"reachable in {ms:.0f} ms:", root)

# %% [markdown]
# ## 2.1 `/skills` — the typeahead path
#
# This runs on every keystroke, so the distribution matters more than the mean:
# a p95 above the 150 ms debounce would be felt as lag.
#
# Queries are split by shape, because the search has three tiers and only
# multi-word queries reach the third (token-wise) one.

# %%
QUERIES = {
    "single, short":  ["p", "py", "sql", "java"],
    "single, long":   ["python", "psychological", "spectroscopy"],
    "multi-word":     ["manage ICT project", "game development",
                       "software architecture", "team building"],
}
REPEATS = 15

rows = []
for shape, qs in QUERIES.items():
    for q in qs:
        for _ in range(REPEATS):
            ms, body = call(f"/skills?q={urllib.parse.quote(q)}&limit=8")
            rows.append({"shape": shape, "query": q, "ms": ms, "hits": len(body)})

skills = pd.DataFrame(rows)
summary = skills.groupby("shape").ms.agg(["median", "mean",
                                          lambda s: s.quantile(0.95), "max"])
summary.columns = ["median_ms", "mean_ms", "p95_ms", "max_ms"]
show(summary.round(1))
show(skills.groupby("query").agg(median_ms=("ms", "median"),
                                    hits=("hits", "first")).round(1))

# %%
fig, (a, b) = plt.subplots(1, 2, figsize=(11, 3.8))

order = list(QUERIES)
# skills["shape"], not skills.shape -- the latter is the DataFrame's
# dimensions, which would silently be the wrong thing.
a.boxplot([skills[skills["shape"] == s].ms for s in order], tick_labels=order)
a.axhline(150, color="crimson", ls="--", lw=1, label="150 ms debounce")
a.set_ylabel("ms"); a.set_title("/skills latency by query shape")
a.legend(); a.grid(alpha=.3)

per_q = skills.groupby("query").ms.median().sort_values()
b.barh(per_q.index.str.slice(0, 24), per_q.values)
b.set_xlabel("median ms"); b.set_title("Per query")
b.grid(alpha=.3, axis="x")

fig.tight_layout()
save(fig, "02_01")

# %% [markdown]
# ## 2.2 `POST /match` — the reasoning path
#
# The API reports its own `seconds`, measured inside `recommend()`. Comparing
# that with the wall-clock time of the HTTP call separates *reasoning* from
# *everything else* (network, TLS, JSON, proxy).
#
# Reasoning cost is not a smooth function of anything obvious, so we use
# several profiles of different shapes rather than repeating one.

# %%
# Resolved by label so the notebook does not carry stale UUIDs.
PROFILES = {
    "clinical (3)":  ["psychological interventions", "therapy in health care",
                      "apply psychological intervention strategies"],
    "software (3)":  ["software architecture models", "ICT system integration",
                      "Python (computer programming)"],
    "optics (6)":    ["optics", "optoelectronics", "optical components",
                      "photonics", "spectroscopy", "lasers"],
    "mixed (4)":     ["manage staff", "quality standards",
                      "perform project management", "data analytics"],
}

def resolve(label):
    _, hits = call(f"/skills?q={urllib.parse.quote(label)}&limit=1")
    return hits[0]["id"] if hits else None

resolved = {}
for name, labels in PROFILES.items():
    ids = [i for i in (resolve(l) for l in labels) if i]
    resolved[name] = ids
    print(f"{name:16} {len(ids)}/{len(labels)} skills resolved")

# %%
rows = []
for name, ids in resolved.items():
    if not ids:
        continue
    try:
        wall, body = call("/match", {"skill_ids": ids}, timeout=300)
        rows.append({
            "profile": name, "skills": len(ids),
            "wall_ms": wall, "reason_ms": body["seconds"] * 1000,
            # max(0, ...): the API rounds its own `seconds` to 2 decimals,
            # so on a local backend where overhead is ~1 ms the rounding can
            # exceed it and produce a negative difference.
            "overhead_ms": max(0.0, wall - body["seconds"] * 1000),
            "shortlist": len(body["shortlist"]),
            "inferred": len(body["occupations"]),
        })
        print(f"{name:16} wall {wall/1000:6.1f}s  reasoning {body['seconds']:6.1f}s "
              f"-> {len(body['occupations'])} inferred")
    except Exception as exc:
        print(f"{name:16} FAILED: {type(exc).__name__} {exc}")

match = pd.DataFrame(rows)
show(match.round(1))

# %%
if not match.empty:
    fig, (a, b) = plt.subplots(1, 2, figsize=(11, 3.8))

    a.bar(match.profile, match.reason_ms / 1000, label="reasoning")
    a.bar(match.profile, match.overhead_ms / 1000,
          bottom=match.reason_ms / 1000, label="network + serialisation")
    a.set_ylabel("seconds"); a.set_title("Where /match time goes")
    a.tick_params(axis="x", rotation=20); a.legend(); a.grid(alpha=.3, axis="y")

    b.scatter(match.shortlist, match.reason_ms / 1000, s=70)
    for _, r in match.iterrows():
        b.annotate(r.profile, (r.shortlist, r.reason_ms / 1000),
                   fontsize=7, xytext=(4, 4), textcoords="offset points")
    b.set_xlabel("occupations shortlisted"); b.set_ylabel("reasoning seconds")
    b.set_title("Shortlist size does NOT predict cost"); b.grid(alpha=.3)

    fig.tight_layout()

    print(f"overhead outside the reasoner: "
          f"median {match.overhead_ms.median():.0f} ms "
          f"({match.overhead_ms.median()/match.wall_ms.median()*100:.1f}% of wall time)")
save(fig, "02_02")

# %% [markdown]
# ## What to take from this
#
# - **`/skills` should sit far below the 150 ms debounce.** If it does not, the
#   in-memory index is not being used, or you are measuring the network rather
#   than the server.
# - **The overhead bar is the honest argument against prefetching the skill
#   list to the client.** If network overhead is tens of milliseconds, shipping
#   0.49 MB of skills to save it is a bad trade.
# - **Shortlist size does not predict reasoning cost.** The right-hand scatter
#   should make that plain: an optics profile with a *smaller* TBox can cost far
#   more than a clinical one. That is why notebook 3 sweeps `min_skills`
#   instead of shortlist size.
