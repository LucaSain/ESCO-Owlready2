"""`/skills` typeahead: the in-memory index, HTTP layer, and ranking rules.

All fast -- the index is built once per session (~0.4s) and every lookup
after that is an in-memory scan.
"""
import esco_store
import matching
import reasoning


# ---------------------------------------------------------------------------
# HTTP layer
# ---------------------------------------------------------------------------

def test_skills_endpoint_returns_matches(client):
    resp = client.get("/skills", params={"q": "assist"})
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) > 0
    assert all(set(row) == {"id", "label"} for row in rows)
    assert all("assist" in row["label"].lower() for row in rows)


def test_skills_endpoint_missing_query_is_422(client):
    # `q` has no default -- omitting it entirely must be a validation error,
    # not a 500 from treating None as a string.
    resp = client.get("/skills")
    assert resp.status_code == 422


def test_skills_endpoint_empty_query_returns_nothing(client):
    resp = client.get("/skills", params={"q": ""})
    assert resp.status_code == 200
    assert resp.json() == []


def test_skills_endpoint_no_match_returns_empty_list(client):
    resp = client.get("/skills", params={"q": "zzzzznotanesco skillxyz"})
    assert resp.status_code == 200
    assert resp.json() == []


def test_skills_endpoint_limit_is_respected(client):
    resp = client.get("/skills", params={"q": "manage", "limit": 3})
    assert resp.status_code == 200
    assert len(resp.json()) == 3


def test_skills_endpoint_limit_out_of_range_is_422(client):
    assert client.get("/skills", params={"q": "manage", "limit": 0}).status_code == 422
    assert client.get("/skills", params={"q": "manage", "limit": 101}).status_code == 422


# ---------------------------------------------------------------------------
# matching.search_skills ranking rules
# ---------------------------------------------------------------------------

def test_search_skills_empty_query_returns_empty_list(store_module):
    assert matching.search_skills("") == []
    assert matching.search_skills("   ") == []


def test_search_skills_prefix_before_substring_shortest_first(store_module):
    """'assist' has skills that start with it (e.g. "assist judge") and
    skills that merely contain it (e.g. "provide victim assistance").
    Requirement: every startswith-match ranks ahead of every merely-contains
    match, and within each group shorter labels rank first."""
    term = "assist"
    # Ask for everything so the split below isn't gated by an arbitrary
    # limit -- we need every start/contains match to check group ordering.
    results = matching.search_skills(term, limit=10_000)
    labels = [row["label"] for row in results]

    is_prefix = [label.lower().startswith(term) for label in labels]
    # Every prefix match precedes every non-prefix match: once we see the
    # first non-prefix label, no prefix label may appear after it.
    first_non_prefix = next((i for i, p in enumerate(is_prefix) if not p), len(is_prefix))
    assert all(is_prefix[:first_non_prefix])
    assert not any(is_prefix[first_non_prefix:])

    # This dataset must actually exercise both groups, or the ordering
    # assertions above would be vacuously true.
    starts, contains = labels[:first_non_prefix], labels[first_non_prefix:]
    assert starts, "expected at least one label starting with 'assist'"
    assert contains, "expected at least one label merely containing 'assist'"

    # Shortest label first within each group.
    lengths_starts = [len(l) for l in starts]
    lengths_contains = [len(l) for l in contains]
    assert lengths_starts == sorted(lengths_starts)
    assert lengths_contains == sorted(lengths_contains)

    # Every result actually contains the term somewhere (sanity: the split
    # above didn't just get lucky).
    assert all(term in label.lower() for label in labels)


def test_search_skills_is_case_insensitive(store_module):
    lower = matching.search_skills("python")
    upper = matching.search_skills("PYTHON")
    mixed = matching.search_skills("PyThOn")
    assert lower == upper == mixed
    assert lower  # sanity: ESCO does have a "Python (computer programming)" skill


def test_search_skills_limit_truncates(store_module):
    unlimited = matching.search_skills("manage", limit=10_000)
    limited = matching.search_skills("manage", limit=5)
    assert len(limited) == 5
    assert limited == unlimited[:5]


# ---------------------------------------------------------------------------
# esco_store.labels_for
# ---------------------------------------------------------------------------

def test_labels_for_empty_input_returns_empty_dict(store_module):
    assert esco_store.labels_for([]) == {}


def _entity_for(store_module, bare_uuid: str):
    # skill_index() returns bare uuids (the public id); resolving through the
    # store needs the full skill IRI -- default_world[<bare uuid>] is simply
    # not present and returns None.
    return store_module.default_world[reasoning.SKILL_NS + bare_uuid]


def test_labels_for_known_skills(store_module):
    # Pull a couple of real entities out of the live index rather than
    # hardcoding IRIs, so this doesn't rot if ESCO ids ever change.
    sample = matching.skill_index()[:3]
    entities = [_entity_for(store_module, skill_id) for skill_id, _ in sample]
    assert all(e is not None for e in entities)

    labels = esco_store.labels_for(entities)
    assert len(labels) == len(entities)
    for (skill_id, expected_label), entity in zip(sample, entities):
        assert labels[entity] == expected_label


def test_labels_for_respects_language_filter(store_module):
    sample = matching.skill_index()[:1]
    entity = _entity_for(store_module, sample[0][0])
    assert entity is not None
    # A language ESCO doesn't carry labels in (as far as this dataset is
    # concerned) must yield nothing for that entity, not raise.
    assert esco_store.labels_for([entity], lang="xx-not-a-real-lang") == {}


class TestMultiWordSearch:
    """Tier 3: every query word matches some label word, in any order.

    Regression: a user types their own phrasing rather than ESCO's, so
    "game development" -- which appears in no ESCO label as a contiguous
    string -- returned nothing at all.
    """

    def test_phrase_absent_from_every_label_still_finds_skills(self, store_module):
        import matching

        hits = matching.search_skills("game development", limit=5)
        assert hits, "expected the token tier to rescue a query with no substring match"
        labels = [h["label"].lower() for h in hits]
        # ESCO says "develop", the user typed "development" -- the
        # bidirectional prefix is what bridges that.
        assert any("develop" in lbl and "game" in lbl for lbl in labels), labels

    def test_case_and_spacing_are_irrelevant(self, store_module):
        import matching

        assert (
            [h["id"] for h in matching.search_skills("Game Development", limit=5)]
            == [h["id"] for h in matching.search_skills("  game   development ", limit=5)]
        )

    def test_strict_tiers_still_rank_first(self, store_module):
        import matching

        # An exact label must not be displaced by looser token matches.
        assert matching.search_skills("manage ICT project", limit=3)[0]["label"] == (
            "manage ICT project"
        )

    def test_single_token_queries_are_unaffected(self, store_module):
        import matching

        # Tier 3 is skipped for single tokens, so this stays exactly as before.
        assert matching.search_skills("python", limit=3)[0]["label"] == (
            "Python (computer programming)"
        )

    def test_short_function_words_do_not_match_everything(self, store_module):
        import matching

        # "of" is below _MIN_RELAX, so it must not relax into every label
        # that happens to contain a 2-letter word.
        hits = matching.search_skills("of zzzznotaskill", limit=5)
        assert hits == []
