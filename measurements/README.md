# Measurements

Four notebooks, each answering one question with numbers rather than
intuition. They are meant to be read in order but run independently.

| notebook | question | needs |
|---|---|---|
| `01_frontend_performance.ipynb` | How fast is the Cloudflare Pages site? | network |
| `02_backend_performance.ipynb` | Where does API latency go? | network, or local backend |
| `03_threshold_and_skillset.ipynb` | How do `min_skills` and profile size drive results and cost? | local quadstore + JRE |
| `04_occupation_depth.ipynb` | Can ESCO's other relations measure a job's depth? | local quadstore |

## Setup

```bash
backend/env/bin/pip install -r measurements/requirements.txt
backend/env/bin/python -m ipykernel install --user --name esco
jupyter lab measurements/          # or open in VS Code and pick the `esco` kernel
```

Notebooks 3 and 4 import `esco_store`, `matching` and `reasoning` from
`backend/`, so they must run with the backend venv's interpreter.

## Costs to know before running

**Notebook 3 is slow and that is the point.** It sweeps `min_skills` from 1
to 10, and reasoning time is not monotonic in any obvious parameter: a
6-skill optics profile takes 2.9s at `min_skills=2` and **117s** at 3. Every
reasoning call is wrapped in a per-call timeout and the cell reports what it
skipped, so a sweep terminates rather than hanging. Budget tens of minutes
and read the timeout column.

**Notebook 1's Lighthouse section needs a PageSpeed Insights API key**
(`PSI_API_KEY`). Keyless requests share a global quota that is usually
exhausted. Everything else in that notebook works without one.
