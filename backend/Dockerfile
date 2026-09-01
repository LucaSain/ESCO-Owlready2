# ESCO reasoner API.
#
# The image carries CODE ONLY. The 1.2 GB quadstore is mounted at runtime --
# see the note at the bottom for why, and for how to build it.

FROM python:3.14-slim AS base

# HermiT is not a library, it is a Java program owlready2 shells out to
# (owlready2.JAVA_EXE). Without a JRE on PATH every /match request fails at
# the reasoning step, while /skills keeps working -- a confusing half-broken
# deploy. headless keeps it to the runtime, no AWT/X11.
RUN apt-get update \
 && apt-get install -y --no-install-recommends default-jre-headless \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first, so a source edit does not re-run pip (and does not
# re-download owlready2's bundled reasoner jars).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./

# Non-root. The reasoner writes an ontology export per request, so it needs
# one writable directory -- ESCO_TMPDIR, not the source tree.
RUN useradd --create-home --uid 10001 app \
 && mkdir -p /tmp/esco /data \
 && chown -R app:app /tmp/esco /data
USER app

ENV ESCO_STORE=/data/esco.sqlite3 \
    ESCO_TMPDIR=/tmp/esco

EXPOSE 8000

# Reasoning is CPU-bound and blocks for seconds, so workers matter more than
# async here. Coolify can override the command to raise --workers; note each
# worker opens its own read-only handle on the quadstore, which is fine, but
# each also builds its own 14k-row skill index in memory.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/',timeout=5).status==200 else 1)"

# ---------------------------------------------------------------------------
# THE QUADSTORE IS NOT IN THIS IMAGE
# ---------------------------------------------------------------------------
# esco.sqlite3 is 1.2 GB. Baking it in would make every push and pull carry
# it, and it changes far less often than the code does. Mount it instead:
#
#   docker run -v esco-data:/data ghcr.io/<owner>/esco-reasoner
#
# To populate the volume once, from a host that has esco.rdf (1.1 GB):
#
#   docker run --rm -v esco-data:/data -v $PWD:/src \
#     ghcr.io/<owner>/esco-reasoner \
#     python ingest.py            # reads ESCO_RDF, writes ESCO_STORE
#
# or just copy a store you already built:
#
#   docker cp esco.sqlite3 <container>:/data/esco.sqlite3
#
# The app opens it READ-ONLY, so the volume can be shared by several
# replicas. If you would rather have a self-contained image, add
#   COPY esco.sqlite3 /data/esco.sqlite3
# above the USER line and accept a ~1.7 GB image.
