"""Rank ESCO occupations by how well a set of skills covers their requirements.

This runs over the data quadstore (esco.sqlite3), not the model TBox: the
41-class ontology declares no occupations or skills to match against. The
whole computation is three grouped SPARQL aggregates, not an OWL reasoner --
there are no class axioms here for a reasoner to exploit.
"""
from esco_store import default_world, iri, sparql, uuid_of

SKILL_NS = "http://data.europa.eu/esco/skill/"

# Essential coverage dominates; optional skills only refine the ranking.
# Putting optional skills in the denominator instead would let an occupation
# that happens to list 70 optional skills outrank a perfect essential match.
ESSENTIAL_WEIGHT = 0.85
OPTIONAL_WEIGHT = 0.15


def resolve_skills(skill_ids):
    """Map skill UUIDs to owlready2 entities, reporting any that don't exist.

    Entities, not IRI strings: owlready2 converts a str SPARQL parameter into
    a literal, so an IRI passed as text silently matches nothing.
    """
    found, unknown = [], []
    for sid in skill_ids:
        entity = default_world[SKILL_NS + sid]
        if entity is None:
            unknown.append(sid)
        else:
            found.append(entity)
    return found, unknown


def _matched(relation, skills):
    return {
        occ: n for occ, n in sparql(
            f"""SELECT ?occ (COUNT(DISTINCT ?s) AS ?n) {{
                  ?occ a esco:Occupation ; esco:{relation} ?s .
                  FILTER(?s IN ??1)
                }} GROUP BY ?occ""",
            [skills],
        )
    }


def _required(relation, occupations):
    return {
        occ: n for occ, n in sparql(
            f"""SELECT ?occ (COUNT(DISTINCT ?s) AS ?n) {{
                  ?occ esco:{relation} ?s .
                  FILTER(?occ IN ??1)
                }} GROUP BY ?occ""",
            [occupations],
        )
    }


def _labels(entities, lang):
    if not entities:
        return {}
    return {
        e: str(form) for e, form in sparql(
            """SELECT ?e ?form {
                 ?e skosxl:prefLabel ?lb . ?lb skosxl:literalForm ?form .
                 FILTER(?e IN ??1 && LANG(?form) = ??2)
               }""",
            [list(entities), lang],
        )
    }


def _gaps(occupations, have, lang):
    # Two queries on purpose. Joining occupation -> skill -> SKOS-XL label in
    # one pattern makes owlready2 plan from the 1.1M skosxl:Label triples and
    # costs ~40s; fetching skill ids first, then labelling only the missing
    # ones, is under a second.
    missing = {occ: [] for occ in occupations}
    for occ, skill in sparql(
        """SELECT ?occ ?s {
             ?occ esco:relatedEssentialSkill ?s .
             FILTER(?occ IN ??1)
           }""",
        [list(occupations)],
    ):
        if skill not in have:
            missing[occ].append(skill)

    labels = _labels({s for skills in missing.values() for s in skills}, lang)
    return {
        occ: sorted(labels.get(s) or uuid_of(s) for s in skills)
        for occ, skills in missing.items()
    }


def match(skill_ids, lang="en", limit=10, min_essential=1, include_gaps=True,
          sort="score"):
    """Rank occupations against a person's skills.

    score  = 0..1, dominated by how much of the occupation's *essential*
             requirement is met; optional coverage only refines it.
    used   = share of the person's own skills the occupation actually uses,
             which separates a narrow exact fit from a broad partial one.

    Occupations listing very few essential skills can reach a high score on
    thin evidence; ties are broken by absolute matches, and min_essential
    raises the bar further.
    """
    skills, unknown = resolve_skills(skill_ids)
    if not skills:
        return {"unknown_skill_ids": unknown, "matches": []}

    have = set(skills)
    matched_ess = _matched("relatedEssentialSkill", skills)
    matched_opt = _matched("relatedOptionalSkill", skills)

    candidates = list(set(matched_ess) | set(matched_opt))
    total_ess = _required("relatedEssentialSkill", candidates)
    total_opt = _required("relatedOptionalSkill", candidates)

    ranked = []
    for occ in candidates:
        ess_n, opt_n = matched_ess.get(occ, 0), matched_opt.get(occ, 0)
        ess_t, opt_t = total_ess.get(occ, 0), total_opt.get(occ, 0)
        if ess_t < min_essential:
            continue
        ess_cov = ess_n / ess_t
        opt_cov = opt_n / opt_t if opt_t else 0.0
        ranked.append({
            "occupation": occ,
            "score": round(ESSENTIAL_WEIGHT * ess_cov + OPTIONAL_WEIGHT * opt_cov, 4),
            "essential_matched": ess_n,
            "essential_total": ess_t,
            "essential_coverage": round(ess_cov, 4),
            "optional_matched": opt_n,
            "optional_total": opt_t,
            "used": round((ess_n + opt_n) / len(skills), 4),
        })

    # A short skill list gives thin evidence, and coverage then favours
    # occupations that simply require few skills. sort="matches" ranks by
    # absolute overlap instead, which is steadier for sparse profiles.
    if sort == "matches":
        ranked.sort(key=lambda r: (-(r["essential_matched"] + r["optional_matched"]),
                                   -r["score"]))
    else:
        ranked.sort(key=lambda r: (-r["score"], -r["essential_matched"]))
    top = ranked[:limit]

    occs = [r["occupation"] for r in top]
    labels = _labels(occs, lang)
    gaps = _gaps(occs, have, lang) if include_gaps else {}

    for r in top:
        occ = r.pop("occupation")
        r["id"] = uuid_of(occ)
        r["iri"] = str(iri(occ))
        r["label"] = labels.get(occ)
        if include_gaps:
            r["missing_essential"] = gaps.get(occ, [])

    return {
        "skills_used": len(skills),
        "unknown_skill_ids": unknown,
        "candidates_considered": len(ranked),
        "matches": top,
    }


def search_skills(q, lang="en", limit=20):
    """Find skill ids by label substring, to feed into match()."""
    rows = sparql(
        """SELECT DISTINCT ?s ?form {
             ?s a esco:Skill ; skosxl:prefLabel ?lb .
             ?lb skosxl:literalForm ?form .
             FILTER(LANG(?form) = ??1 && CONTAINS(LCASE(?form), ??2))
           } LIMIT """ + str(int(limit)),
        [lang, q.lower()],
    )
    return [{"id": uuid_of(s), "label": str(form)} for s, form in rows]
