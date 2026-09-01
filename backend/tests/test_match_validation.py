"""POST /match request validation that never reaches the reasoner.

reasoning.recommend() checks "does every skill id resolve" before it does
anything expensive (SPARQL shortlist, TBox build, HermiT) -- so an
all-bogus-ids request 422s in microseconds. These stay in the fast tier on
purpose; do not add a case here that lets any real occupation shortlist form
(that starts costing real reasoner time / becomes `slow`).
"""


def test_empty_skill_ids_list_is_422(client):
    resp = client.post("/match", json={"skill_ids": []})
    assert resp.status_code == 422


def test_missing_skill_ids_field_is_422(client):
    resp = client.post("/match", json={})
    assert resp.status_code == 422


def test_all_bogus_skill_ids_is_422(client):
    resp = client.post("/match", json={
        "skill_ids": ["not-a-real-skill-id", "also-fake-00000000-0000-0000-0000-000000000000"],
    })
    assert resp.status_code == 422
    assert "none of the given skill ids exist" in resp.json()["detail"]


def test_shortlist_below_minimum_is_422(client):
    resp = client.post("/match", json={"skill_ids": ["irrelevant"], "shortlist": 0})
    assert resp.status_code == 422


def test_shortlist_above_maximum_is_422(client):
    # Field caps at 40: above that HermiT stops terminating (see reasoning.py).
    resp = client.post("/match", json={"skill_ids": ["irrelevant"], "shortlist": 41})
    assert resp.status_code == 422


def test_min_skills_below_minimum_is_422(client):
    resp = client.post("/match", json={"skill_ids": ["irrelevant"], "min_skills": 0})
    assert resp.status_code == 422


def test_skill_ids_must_be_a_list(client):
    resp = client.post("/match", json={"skill_ids": "not-a-list"})
    assert resp.status_code == 422
