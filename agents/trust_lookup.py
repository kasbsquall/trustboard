"""Reading the Trust Score back from the DataHub graph.

Reads what the Scribe wrote: structured properties on domains and on datasets,
plus the dataset tier tag. The MCP server and the Gatekeeper agent consume these
functions, which is how the trust knowledge TrustBoard produced gets inherited
by other agents.

The policy decision lives here, and it has three outcomes rather than two.
"Rated below the bar" and "we have no score for this" are different facts and a
caller has to be able to tell them apart: the first is a judgement about the
data, the second is a gap in the catalog. Collapsing them into trustworthy=False
means the first asset anyone points TrustBoard at gets blocked for the crime of
being new, and that is how a governance tool gets switched off in week two. The
default is still to block on unrated, because failing open on a governance
check is worse, but the answer says which of the two happened and the policy is
a parameter.
"""
from __future__ import annotations

from mcp_client.datahub_connection import execute_graphql_retry, get_graph

PROP_SCORE = "urn:li:structuredProperty:io.trustboard.trustScore"
PROP_TIER = "urn:li:structuredProperty:io.trustboard.trustTier"
PROP_COVERAGE = "urn:li:structuredProperty:io.trustboard.trustCoverage"
PROP_VERSION = "urn:li:structuredProperty:io.trustboard.trustScoreVersion"

_TIER_RANK = {"at-risk": 0, "bronze": 1, "silver": 2, "gold": 3}

# What to do about an asset TrustBoard could not rate.
UNRATED_POLICIES = ("block", "allow", "warn")

_SP_FRAGMENT = """
      structuredProperties { properties {
        structuredProperty { urn }
        values { ... on NumberValue { numberValue } ... on StringValue { stringValue } }
      } }
"""

# `exists` is queried on Dataset because DataHub answers with a populated stub
# for any well-formed URN it has never seen. Without it, a typo in a URN comes
# back as an asset with no score, indistinguishable from a real dataset nobody
# has rated. Domain has no such field in this GMS version, and the domain path is
# only reached through a URN the dataset itself reported, so it is not needed there.
_DOMAIN_SP = """
query d($urn: String!) {
  domain(urn: $urn) {
    properties { name }
%s
  }
}
""" % _SP_FRAGMENT

_DATASET_TRUST = """
query ds($urn: String!) {
  dataset(urn: $urn) {
    exists
    name
    tags { tags { tag { urn } } }
    domain { domain { urn properties { name } } }
%s
  }
}
""" % _SP_FRAGMENT

_LEADERBOARD = """
query l($start: Int!, $count: Int!) {
  search(input: {type: DOMAIN, query: "*", start: $start, count: $count}) {
    total
    searchResults { entity { urn ... on Domain {
      properties { name }
%s
    } } }
  }
}
""" % _SP_FRAGMENT

_PAGE = 100


def _extract_sp(structured_properties: dict | None) -> dict:
    """Pulls TrustBoard's structured properties out of a GraphQL response."""
    out: dict = {"trust_score": None, "trust_tier": None, "coverage": None, "score_version": None}
    if not structured_properties:
        return out
    for p in structured_properties.get("properties", []):
        purn = p["structuredProperty"]["urn"]
        values = p.get("values") or []
        if not values:
            continue
        v = values[0]
        if purn == PROP_SCORE and "numberValue" in v:
            out["trust_score"] = round(v["numberValue"], 2)  # clean up float precision
        elif purn == PROP_TIER and "stringValue" in v:
            out["trust_tier"] = v["stringValue"]
        elif purn == PROP_COVERAGE and "numberValue" in v:
            out["coverage"] = round(v["numberValue"], 2)
        elif purn == PROP_VERSION and "stringValue" in v:
            out["score_version"] = v["stringValue"]
    return out


def read_domain_trust(urn: str, graph=None) -> dict:
    """Trust Score of a domain (team), read from its structured properties."""
    graph = graph or get_graph()
    dom = execute_graphql_retry(graph, _DOMAIN_SP, variables={"urn": urn}).get("domain")
    # A domain with no name is a stub DataHub minted for a URN it has never
    # seen. Domain carries no `exists` field in this GMS version, and treating
    # the stub as real meant a typo in a domain URN came back as an existing but
    # unrated asset, which `on_unrated="allow"` then waved through. A governance
    # gate that fails open on a misspelling is worse than no gate.
    if not dom or not (dom.get("properties") or {}).get("name"):
        return {"urn": urn, "found": False}
    sp = _extract_sp(dom.get("structuredProperties"))
    return {
        "urn": urn,
        "kind": "domain",
        "name": (dom.get("properties") or {}).get("name"),
        **sp,
        "found": sp["trust_score"] is not None,
    }


def read_dataset_trust(urn: str, graph=None) -> dict:
    """Dataset trust: its own score and tier, plus the owning team's score.

    The dataset's own structured properties are what matter for a decision about
    that dataset. The team score is context, useful for a human reading the
    answer, and the tag is a fallback for a graph scored by an older Scribe that
    only wrote tags at this level.
    """
    graph = graph or get_graph()
    ds = execute_graphql_retry(graph, _DATASET_TRUST, variables={"urn": urn}).get("dataset")
    if not ds or ds.get("exists") is False:
        return {"urn": urn, "found": False}

    sp = _extract_sp(ds.get("structuredProperties"))

    tag_tier = None
    for t in ((ds.get("tags") or {}).get("tags") or []):
        tag_urn = t["tag"]["urn"]
        if tag_urn.startswith("urn:li:tag:trust."):
            tag_tier = tag_urn.rsplit(".", 1)[-1]
            break

    domain_block = (ds.get("domain") or {}).get("domain") or {}
    domain_urn = domain_block.get("urn")
    domain_trust = read_domain_trust(domain_urn, graph=graph) if domain_urn else {}

    # The tag is a badge TrustBoard puts on for people browsing the catalog. It
    # is not evidence, because anyone with edit rights can apply it by hand from
    # the DataHub UI, and it was read as an authority equal to the property
    # TrustBoard itself wrote: a self-applied `trust.gold` came back as
    # `status: "rated", trustworthy: true` with a null score behind it, so the
    # gate could be opened by the very team it was meant to check. The tag is
    # accepted only when TrustBoard's own write corroborates it, which is what
    # score_version proves. Anything else is unrated, the honest answer for an
    # asset nobody has measured.
    # Neither the property nor the tag is evidence on its own. Both are editable
    # from the DataHub UI with ordinary catalog permissions, so a team that
    # dislikes its rating can hand-set io.trustboard.trustTier to "gold" and, with
    # the tier read at face value, the gate answered `status: "rated",
    # trustworthy: true` with a null score and a null model version sitting right
    # there in the response. The first version of this guard covered the tag and
    # left the property, which takes precedence, wide open.
    #
    # score_version is the corroboration because only the Scribe writes it, and it
    # writes it in the same mutation as the score. A tier without one is a claim
    # nobody can back, and the honest answer for a claim nobody can back is that
    # we have not measured this asset.
    corroborated = bool(sp["score_version"])
    tier = (sp["trust_tier"] or tag_tier) if corroborated else None
    return {
        "urn": urn,
        "kind": "dataset",
        "name": ds.get("name"),
        "trust_score": sp["trust_score"],
        "trust_tier": tier,
        "coverage": sp["coverage"],
        "score_version": sp["score_version"],
        "owning_team": domain_trust.get("name"),
        "team_trust_score": domain_trust.get("trust_score"),
        "found": tier is not None,
    }


def read_trust(urn: str, graph=None) -> dict:
    """Dispatches to domain or dataset depending on the urn type."""
    if urn.startswith("urn:li:domain:"):
        return read_domain_trust(urn, graph=graph)
    if urn.startswith("urn:li:dataset:"):
        return read_dataset_trust(urn, graph=graph)
    return {"urn": urn, "found": False, "error": "unsupported entity type"}


def is_trustworthy(
    urn: str,
    min_tier: str = "silver",
    on_unrated: str = "block",
    graph=None,
) -> dict:
    """GO/NO-GO policy: does the asset reach the minimum trust tier?

    Returns `status` alongside `trustworthy`, one of:
      rated      - TrustBoard has a score, and trustworthy reflects it
      unrated    - the asset exists but TrustBoard could not judge it
      not_found  - no such asset in the graph

    Every input to the decision comes back in the response, so the caller can
    log a decision that is reproducible later instead of a bare boolean nobody
    can audit.

    Raises ValueError on an unknown min_tier or policy. A typo used to fall
    through to a default silently, which means a caller asking for `gold` and
    misspelling it got a laxer gate than they asked for and no warning.
    """
    if min_tier not in _TIER_RANK:
        raise ValueError(
            f"unknown min_tier {min_tier!r}; expected one of {sorted(_TIER_RANK)}"
        )
    if on_unrated not in UNRATED_POLICIES:
        raise ValueError(
            f"unknown on_unrated {on_unrated!r}; expected one of {list(UNRATED_POLICIES)}"
        )

    info = read_trust(urn, graph=graph)
    policy = {"min_tier": min_tier, "on_unrated": on_unrated}

    if info.get("error") or not info.get("kind"):
        return {
            **info,
            "trustworthy": False,
            "status": "not_found",
            "reason": info.get("error") or "asset not found in DataHub",
            "policy": policy,
        }

    tier = info.get("trust_tier")

    if tier is None or tier == "unrated":
        allowed = on_unrated in ("allow", "warn")
        if tier is None:
            detail = "TrustBoard has not scored this asset yet"
        else:
            cov = info.get("coverage")
            detail = (
                "TrustBoard could not judge this asset: signal coverage was "
                + (f"{cov:.0%}" if isinstance(cov, (int, float)) else "too low")
            )
        return {
            **info,
            "trustworthy": allowed,
            "status": "unrated",
            "reason": f"{detail}. Policy on unrated assets is '{on_unrated}'.",
            "policy": policy,
        }

    if tier not in _TIER_RANK:
        return {
            **info,
            "trustworthy": False,
            "status": "unrated",
            "reason": (
                f"tier {tier!r} is not one of {sorted(_TIER_RANK)}, so it cannot "
                "be compared against the policy"
            ),
            "policy": policy,
        }

    ok = _TIER_RANK[tier] >= _TIER_RANK[min_tier]
    reason = (
        f"tier '{tier}' meets minimum '{min_tier}'"
        if ok
        else f"tier '{tier}' is below minimum '{min_tier}'"
    )
    return {**info, "trustworthy": ok, "status": "rated", "reason": reason, "policy": policy}


def leaderboard(graph=None) -> list[dict]:
    """Team ranking by Trust Score, read from the graph.

    Paged, so an instance with more than one page of domains ranks all of them
    rather than whichever page came back first.
    """
    graph = graph or get_graph()
    teams = []
    start = 0
    while True:
        page = execute_graphql_retry(
            graph, _LEADERBOARD, variables={"start": start, "count": _PAGE}
        )["search"]
        results = page.get("searchResults") or []
        for r in results:
            e = r["entity"]
            sp = _extract_sp(e.get("structuredProperties"))
            if sp["trust_score"] is not None and sp["trust_tier"] != "unrated":
                teams.append(
                    {
                        "name": (e.get("properties") or {}).get("name"),
                        "trust_score": sp["trust_score"],
                        "trust_tier": sp["trust_tier"],
                        "coverage": sp["coverage"],
                    }
                )
        start += _PAGE
        if not results or start >= (page.get("total") or 0):
            break
    teams.sort(key=lambda t: t["trust_score"], reverse=True)
    return teams
