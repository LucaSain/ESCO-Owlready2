"""Shared helpers for the measurement scripts.

These run as plain Python, not in a notebook, so the two things a notebook
gave us for free need replacing:

  * `display(df)` -> `show(df)`, which prints the whole frame instead of
    pandas' truncated repr.
  * inline plots -> `save(fig, name)`, which writes a PNG into figures/ and
    prints the path. matplotlib is forced onto the Agg backend so this works
    over SSH or in a container with no display.

The `# %%` markers in each script are cell separators. Run the files
normally, or step through them cell by cell in VS Code / PyCharm / Spyder.
"""
import os
from pathlib import Path

import matplotlib

# Must precede pyplot: without a display, the default backend raises.
matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

FIGURES = Path(__file__).parent / "figures"
FIGURES.mkdir(exist_ok=True)


def show(obj, floatfmt="{:.3f}"):
    """Print a DataFrame or Series in full, rather than pandas' abbreviation."""
    if isinstance(obj, (pd.DataFrame, pd.Series)):
        with pd.option_context("display.max_rows", 200,
                               "display.max_columns", 50,
                               "display.width", 200,
                               "display.float_format", floatfmt.format):
            print(obj.to_string())
    else:
        print(obj)
    print()


def save(fig, name):
    """Write a figure to figures/<name>.png and say where it went."""
    path = FIGURES / f"{name}.png"
    fig.savefig(path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    print(f"  [figure] {path.relative_to(Path(__file__).parent.parent)}")
    return path


def reason_with_timeout(skill_ids, min_skills, shortlist=20, timeout=150):
    """Run one reasoning call with a hard wall-clock budget.

    Returns (seconds, n_inferred, n_shortlist, timed_out).

    Uses a subprocess in its OWN PROCESS GROUP, not a thread, because
    owlready2 spawns HermiT as a JVM grandchild. A thread-based timeout can
    only stop *waiting* -- the JVM keeps running and burning CPU, which then
    starves every later call in a sweep. That is not hypothetical: an early
    version of script 03 reported min_skills 5..10 as all timing out, when in
    fact only 5 was slow and 7 and 10 finish in a few seconds. The timeouts
    were abandoned JVMs from the one genuinely slow call.
    """
    import json as _json
    import signal
    import subprocess
    import sys
    import time as _time

    worker = Path(__file__).parent / "_worker.py"
    proc = subprocess.Popen(
        [sys.executable, str(worker), _json.dumps(list(skill_ids)),
         str(min_skills), str(shortlist)],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        start_new_session=True,          # its own process group to kill
    )
    started = _time.perf_counter()
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        # Kill the whole group, so the JVM goes too.
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        proc.wait()
        return float(timeout), float("nan"), float("nan"), True

    elapsed = _time.perf_counter() - started
    for line in (out or "").splitlines():
        if line.startswith("__RESULT__"):
            r = _json.loads(line[len("__RESULT__"):])
            return elapsed, r["inferred"], r["shortlist"], False
    return elapsed, float("nan"), float("nan"), False


def heading(text):
    print(f"\n{'=' * 72}\n{text}\n{'=' * 72}")
