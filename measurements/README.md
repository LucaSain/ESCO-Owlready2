# Measurements

Four scripts, each answering one question with numbers rather than intuition.
They are plain Python — no Jupyter needed.

| script | question | needs |
|---|---|---|
| `01_frontend_performance.py` | How fast is the Cloudflare Pages site? | network |
| `02_backend_performance.py` | Where does API latency go? | a running backend |
| `03_threshold_and_skillset.py` | How do `min_skills` and profile size drive results and cost? | local quadstore + JRE |
| `04_occupation_depth.py` | Can ESCO's other relations measure a job's depth? | local quadstore |

## Running them

```bash
backend/env/bin/pip install -r measurements/requirements.txt
backend/env/bin/python measurements/04_occupation_depth.py
```

Scripts 3 and 4 import `esco_store`, `matching` and `reasoning` from
`backend/`, so they need that interpreter — not a system Python.

Figures are written to `measurements/figures/` as PNGs, since there is no
notebook to render them inline. Each `save()` prints the path it wrote.

The `# %%` markers are cell separators. Run the files normally, or step
through them cell by cell in VS Code, PyCharm or Spyder if you prefer.

## Configuration

| variable | script | default |
|---|---|---|
| `SITE_URL` | 01 | `https://esco.lucasain.dev` |
| `API_URL` | 02 | `http://localhost:8000` |
| `REASON_TIMEOUT` | 03 | `150` (seconds per reasoning call) |

Pointing `API_URL` at the deployed API folds in Cloudflare and network RTT;
leaving it local isolates the reasoner. The gap between the two *is* the
network cost, so both runs are worth having.

## Costs to know before running

**Script 03 is slow, and that is the finding.** It sweeps `min_skills` from 1
to 10, and cost is not monotonic in any cheap-to-measure parameter: a 6-skill
optics profile takes 2.9 s at `min_skills=2` and **117 s** at 3. Every
reasoning call has a wall-clock budget (`REASON_TIMEOUT`) and the tables
record what timed out, so a sweep terminates instead of hanging. Budget tens
of minutes, and read the `timed_out` column before the graphs.

A caveat stated in the script too: a timed-out call is *abandoned*, not
killed, so a JVM finishes in the background. Fine for measurement, not
something the API should do.

## The finding in script 03

Cost spikes at the *boundary*, not above it. On a 6-skill profile:

```
min_skills=1    2.7s  -> 20 inferred
min_skills=4    7.8s  ->  3
min_skills=5   45.0s  TIMED OUT     <- the spike
min_skills=6   45.0s  TIMED OUT
min_skills=7    3.1s  ->  0
min_skills=10   5.9s  ->  0
```

Below the boundary the reasoner only has to *find* a model and can stop at
the first one. Far above it (7 > 6 asserted skills) the request is
arithmetically hopeless and gets rejected quickly. At 5-6 it is neither: the
reasoner must decide whether some selection of 5 distinct fillers exists
across enumerations of ~99 skills, and under the Open World Assumption it
cannot assume the candidate lacks the ~93 skills nobody asserted. So it
searches, exhaustively.

Adding a closure axiom (`hasSkill only {the asserted skills}`) confirms OWA
is part of the cost: at `min_skills=5` that takes the run from **timeout** to
**36s**. Still slow, but decidable.

## Results worth knowing before you start

Script 04 produces a **negative result**, which is why it is worth keeping.
Validated against ISCO major groups — which none of its proxies touch:

```
n_essential      vs ISCO:  -0.357   simplest signal, strongest
mean_ancestors           :  -0.133
depth_index (composite)  :  +0.045   no relationship
mean_idf                 :  +0.193   WRONG DIRECTION
```

Skill rarity measures niche-ness, not expertise. Merely counting essential
skills beats every construct built on top of it. The script says so.

## Lighthouse

Deliberately not automated — run it from the browser or PageSpeed Insights.
Script 01 measures TTFB, cache status and transfer size, which is what a
static export can actually act on.
