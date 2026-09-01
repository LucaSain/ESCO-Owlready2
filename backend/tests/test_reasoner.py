"""Tests that exercise the real HermiT reasoner via reasoning.recommend and
POST /match.

Every test in this module is @pytest.mark.slow: each call to reasoning.infer
spawns a Java subprocess and measured ~3.5s on the six-skill fixture below.
Run explicitly with `pytest -m slow` (excluded from the default run).

Fixture: the six essential skills of "assistant clinical psychologist" in
ESCO. With min_skills=3 the reasoner must classify the candidate into both
"clinical psychologist" and "assistant clinical psychologist" -- confirmed
manually against this exact store before writing these assertions.
"""
import pytest

import reasoning

pytestmark = pytest.mark.slow

ESSENTIAL_SKILL_UUIDS = [
    "e9e08a59-f697-434c-a955-39623650be9d",
    "b9b572bf-5e50-4588-8aa0-a42a49332467",
    "98eb1f3b-3480-416b-bd4b-811946f7e347",
    "110833ee-c4f1-4856-9b7f-7e49ffda537f",
    "8f5d6a1b-32fa-4c3f-b3d6-5f070d2e0f74",
    "604fa3e6-bc8d-423e-b7e8-c0ba2416eaa4",
]
ESSENTIAL_SKILL_IRIS = [reasoning.SKILL_NS + u for u in ESSENTIAL_SKILL_UUIDS]

EXPECTED_OCCUPATIONS = {"clinical psychologist", "assistant clinical psychologist"}


def _assert_graph_contract(body):
    """The response's own internal consistency, independent of which
    occupations happened to be inferred:
      * every id a shortlist entry cites in matched_skills must be an id
        actually present in skills[]
      * inferred is true for a shortlist entry iff its label is in
        occupations
    """
    skill_ids = {s["id"] for s in body["skills"]}
    assert skill_ids, "expected at least one resolved skill in the response"

    occupations = set(body["occupations"])
    for entry in body["shortlist"]:
        for matched_id in entry["matched_skills"]:
            assert matched_id in skill_ids, (
                f"shortlist entry {entry['id']} ({entry['label']!r}) cites "
                f"matched_skills id {matched_id!r} that is not in skills[]"
            )
        assert entry["inferred"] == (entry["label"] in occupations), (
            f"shortlist entry {entry['label']!r}: inferred={entry['inferred']!r} "
            f"but membership in occupations is {entry['label'] in occupations}"
        )


@pytest.fixture(scope="module")
def match_response(client):
    """One /match call, shared by every test below that only needs to read
    the result -- avoids paying for the reasoner more than once for the
    core fixture. Also exercises bare-UUID skill_ids (as opposed to full
    IRIs), which /match must accept per main.py's _as_iri."""
    resp = client.post("/match", json={
        "skill_ids": ESSENTIAL_SKILL_UUIDS,
        "min_skills": 3,
    })
    assert resp.status_code == 200
    return resp.json()


def test_match_infers_expected_occupations(match_response):
    occupations = set(match_response["occupations"])
    assert EXPECTED_OCCUPATIONS <= occupations


def test_match_resolves_all_six_skills(match_response):
    assert match_response["skills_used"] == 6
    assert match_response["unknown_skill_ids"] == []
    assert match_response["skills_not_required"] == []
    assert len(match_response["skills"]) == 6


def test_match_reports_positive_elapsed_seconds(match_response):
    # Sanity that `seconds` reflects real reasoning work, not a stub.
    assert match_response["seconds"] > 0


def test_match_graph_contract(match_response):
    _assert_graph_contract(match_response)


def test_match_shortlist_entries_for_expected_occupations_are_inferred(match_response):
    by_label = {e["label"]: e for e in match_response["shortlist"]}
    for label in EXPECTED_OCCUPATIONS:
        assert label in by_label, f"expected {label!r} to appear in the shortlist at all"
        assert by_label[label]["inferred"] is True


def test_recommend_function_directly_with_full_iris_and_one_bogus_id(store_module):
    """Exercises reasoning.recommend (not the HTTP layer), with full skill
    IRIs, and one deliberately-invalid id mixed in -- checking that partial
    resolution still works: the bogus id is reported as unknown, the other
    six still resolve and drive inference to the same conclusion."""
    skill_ids = ESSENTIAL_SKILL_IRIS + ["http://data.europa.eu/esco/skill/not-a-real-skill"]

    result = reasoning.recommend(skill_ids, min_skills=3)

    assert result["unknown_skill_ids"] == ["http://data.europa.eu/esco/skill/not-a-real-skill"]
    assert result["skills_used"] == 6
    assert EXPECTED_OCCUPATIONS <= set(result["occupations"])
    _assert_graph_contract(result)
