import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import esco_store as store
import matching
import reasoning

SKILL_NS = reasoning.SKILL_NS


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Opens the prebuilt quadstore read-only. No parsing, and no reasoner:
    # reasoning happens per request over a small generated ontology.
    store.open_store()
    print(f"store : {store.STORE_PATH} ({len(store.default_world.graph):,} triples, read-only)")
    # Build the typeahead index now so the first keystroke isn't the one
    # that pays for it.
    print(f"skills: {len(matching.skill_index()):,} indexed")
    print(f"cors  : {CORS_ORIGINS} regex={CORS_ORIGIN_REGEX}")
    yield


app = FastAPI(title="ESCO Reasoner", lifespan=lifespan)

# The browser preflights every POST here, because the frontend is always a
# different origin: :3000 in dev, a *.pages.dev or custom domain in prod.
#
# Configured from the environment, not hardcoded, because the deployed origin
# is not known until Cloudflare Pages exists -- and baking it in would mean a
# rebuild to change it. In Coolify, set:
#
#   CORS_ORIGINS=https://your-project.pages.dev,https://yourdomain.com
#
# CORS_ORIGIN_REGEX additionally covers Cloudflare Pages *preview* deploys,
# which get a per-commit hostname like https://a1b2c3d4.your-project.pages.dev
# and can therefore never be enumerated:
#
#   CORS_ORIGIN_REGEX=https://.*\.your-project\.pages\.dev
#
# Note it is fullmatch-ed, so anchor it and escape the dots -- an unescaped
# "." matches any character and https://evil-yourproject.pages.dev would pass.
CORS_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    ).split(",")
    if origin.strip()
]
CORS_ORIGIN_REGEX = os.environ.get("CORS_ORIGIN_REGEX") or None

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_origin_regex=CORS_ORIGIN_REGEX,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
    # Left off deliberately. There are no cookies or auth headers here, and
    # allow_credentials=True is incompatible with a wildcard origin -- so
    # turning it on later is a decision, not a default.
    allow_credentials=False,
)


@app.get("/")
async def root():
    return {
        "store": str(store.STORE_PATH),
        "triples": len(store.default_world.graph),
        "skills_indexed": len(matching.skill_index()),
    }


@app.get("/skills")
async def skills(q: str, lang: str = "en", limit: int = Query(20, ge=1, le=100)):
    """Typeahead: find skill ids by label, to build a profile for /match."""
    return matching.search_skills(q, lang, limit)


class Profile(BaseModel):
    skill_ids: list[str] = Field(
        ..., min_length=1, description="ESCO skill UUIDs or full IRIs, from /skills")
    shortlist: int = Field(
        reasoning.DEFAULT_SHORTLIST, ge=1, le=40,
        description="occupations handed to the reasoner; above ~40 it stops terminating")
    min_skills: int = Field(
        reasoning.DEFAULT_MIN_SKILLS, ge=1,
        description="how many of an occupation's essential skills a candidate must hold")
    lang: str = "en"


def _as_iri(skill_id: str) -> str:
    """Accept either a bare UUID (what /skills returns) or a full IRI."""
    return skill_id if skill_id.startswith("http") else SKILL_NS + skill_id


# Deliberately `def`, not `async def`. The reasoner blocks for seconds and
# spawns a JVM; FastAPI runs a sync endpoint in a threadpool, so it does not
# stall the event loop for every other request.
@app.post("/match")
def match(profile: Profile):
    """Recommend occupations by classifying the candidate with a DL reasoner.

    SPARQL narrows ESCO's 3,046 occupations to a shortlist, those become OWL
    defined classes, the candidate is asserted as an individual, and HermiT
    classifies it. Expect a few seconds -- this is inference, not a query.
    """
    try:
        return reasoning.recommend(
            [_as_iri(s) for s in profile.skill_ids],
            shortlist=profile.shortlist,
            min_skills=profile.min_skills,
            lang=profile.lang,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
