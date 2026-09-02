"""1. Frontend performance — Cloudflare Pages

Generated from the notebook of the same name. Runs as a plain script:

    backend/env/bin/python measurements/01_frontend_performance.py

The `# %%` markers are cell separators -- step through them in VS Code,
PyCharm or Spyder if you prefer, or just run the file.

Figures are written to measurements/figures/ rather than shown inline.
"""


# %% [markdown]
# # 1. Frontend performance — Cloudflare Pages
#
# The site is a static export (41 files, ~936 KB) served from Cloudflare's edge.
# There is no server render, so the questions worth asking are narrow:
#
# 1. **Time to first byte**, cold and warm — does the edge cache actually serve us?
# 2. **Transfer size** — is compression on, and is the JS budget sane?
# 3. **Lighthouse** — the synthetic score, for comparability with other sites.
#
# TTFB and sizes need nothing but network access. Lighthouse needs a
# PageSpeed Insights key (`PSI_API_KEY`); without one the request shares a
# global quota that is normally exhausted.

# %%
import json, os, statistics, time, urllib.request, gzip, io
import matplotlib.pyplot as plt

from common import heading, save, show
import pandas as pd

SITE = os.environ.get("SITE_URL", "https://esco.lucasain.dev")
REPEATS = 12

# Cloudflare rejects Python's default User-Agent with a 403. This is the same
# trap that made the iso25964 ontology look unreachable earlier: the resource
# is fine, urllib is what is being refused.
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) esco-measurements/1.0"}

print("target:", SITE)

# %% [markdown]
# ## 1.1 Time to first byte
#
# `REPEATS` sequential requests. The first is expected to be slower: a cold
# edge cache, plus TLS and connection setup that later requests may reuse.
# We record Cloudflare's own `cf-cache-status` header so a slow sample can be
# attributed rather than guessed at.

# %%
def timed_get(url, headers=None):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=30) as r:
        first = time.perf_counter() - t0          # header arrival ~= TTFB
        body = r.read()
        total = time.perf_counter() - t0
        return {
            "ttfb_ms": first * 1000,
            "total_ms": total * 1000,
            "bytes": len(body),
            "cache": r.headers.get("cf-cache-status", "-"),
            "encoding": r.headers.get("content-encoding", "none"),
        }

samples = [timed_get(SITE) for _ in range(REPEATS)]
df = pd.DataFrame(samples)
df.index.name = "request"
show(df.round(1))

warm = df.iloc[1:]
print(f"cold  TTFB : {df.ttfb_ms.iloc[0]:.0f} ms")
print(f"warm  TTFB : median {warm.ttfb_ms.median():.0f} ms, "
      f"p95 {warm.ttfb_ms.quantile(0.95):.0f} ms")
print(f"cache statuses seen: {df.cache.value_counts().to_dict()}")

# %%
fig, (a, b) = plt.subplots(1, 2, figsize=(11, 3.6))

a.plot(df.index, df.ttfb_ms, marker="o", label="TTFB")
a.plot(df.index, df.total_ms, marker="s", alpha=.6, label="full response")
a.set_xlabel("request #"); a.set_ylabel("ms")
a.set_title("Latency across sequential requests")
a.legend(); a.grid(alpha=.3)

b.boxplot([df.ttfb_ms.iloc[1:]], tick_labels=["warm TTFB"])
b.scatter([1], [df.ttfb_ms.iloc[0]], color="crimson", zorder=3, label="cold (1st)")
b.set_ylabel("ms"); b.set_title("Cold vs warm"); b.legend(); b.grid(alpha=.3)

fig.tight_layout()
save(fig, "01_01")

# %% [markdown]
# ## 1.2 Transfer size and compression
#
# A static export's cost is almost entirely its assets. Here we walk the HTML,
# pull every `_next/static` reference, and record compressed versus
# uncompressed size. Uncompressed JS is what the browser must *parse*, which is
# the part that shows up as Total Blocking Time.

# %%
import re

html = urllib.request.urlopen(
    urllib.request.Request(SITE, headers=UA), timeout=30).read().decode()
assets = sorted(set(re.findall(r'/_next/static/[A-Za-z0-9_./-]+\.(?:js|css)', html)))
print(f"{len(assets)} static assets referenced")

rows = []
for path in assets:
    url = SITE.rstrip("/") + path

    # Two requests per asset, because one cannot answer both questions.
    # Cloudflare serves brotli here, and decompressing br would need an extra
    # dependency -- so instead ask for identity encoding to get the true
    # uncompressed size directly from the origin.
    def fetch(encoding):
        req = urllib.request.Request(url, headers={**UA, "Accept-Encoding": encoding})
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read(), r.headers.get("content-encoding", "none")

    compressed, enc = fetch("br, gzip")
    plain, _ = fetch("identity")

    rows.append({"asset": path.split("/")[-1], "kind": path.rsplit(".", 1)[-1],
                 "wire_kb": len(compressed) / 1024,
                 "parsed_kb": len(plain) / 1024,
                 "ratio": len(compressed) / max(len(plain), 1),
                 "encoding": enc})

sizes = pd.DataFrame(rows).sort_values("wire_kb", ascending=False)
show(sizes.round(1))
print(f"total on the wire : {sizes.wire_kb.sum():.0f} KB")
print(f"total to parse    : {sizes.parsed_kb.sum():.0f} KB "
      f"({sizes.wire_kb.sum()/sizes.parsed_kb.sum():.0%} of it after compression)")
print(f"page HTML         : {len(html)/1024:.1f} KB")

# %%
fig, (a, b) = plt.subplots(1, 2, figsize=(11, 3.8))

top = sizes.head(8).iloc[::-1]
a.barh(top.asset.str.slice(0, 26), top.wire_kb)
a.set_xlabel("KB on the wire"); a.set_title("Largest assets")
a.grid(alpha=.3, axis="x")

by_kind = sizes.groupby("kind")[["wire_kb", "parsed_kb"]].sum()
by_kind.plot(kind="bar", ax=b, rot=0)
b.set_ylabel("KB"); b.set_title("Wire vs parsed, by type")
b.grid(alpha=.3, axis="y")

fig.tight_layout()
save(fig, "01_02")

# %% [markdown]
# ## What to take from this
#
# Fill in after running. The things worth writing down:
#
# - **Warm TTFB** is the number that represents the edge. If it is not well
#   under 100 ms, the cache is not doing its job — check `cf-cache-status`.
# - **Cold vs warm gap** is TLS plus cache miss. A large gap on a static site
#   usually means low traffic rather than a problem.
# - **Parsed KB** matters more than wire KB for interactivity. The graph view
#   is hand-rolled SVG precisely to keep this small: no d3, no chart library.
# - A near-100 Lighthouse score is expected for a static export and is not
#   evidence of much. The interesting comparison is *before and after* adding
#   a dependency.
