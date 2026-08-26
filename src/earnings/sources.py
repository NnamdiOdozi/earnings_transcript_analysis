"""Provider-agnostic (Exa/Tavily) web search/extraction and limited SEC filing/XBRL retrieval.

Both are thin wrappers around httpx calls. Callers (cli.py) decide whether to invoke
them at all -- Tavily is only called when external web evidence is explicitly
requested, and SEC lookups are opt-in per the `--sec-ticker`/`--sec-cik` CLI flags.
Tests never call these functions; they build evidence/financials.json from fixtures
directly, so no network guard flag is needed inside the functions themselves.
"""
from __future__ import annotations

from typing import Any

import httpx

from .config import (
    EXA_CONTENTS_URL,
    EXA_SEARCH_URL,
    HTTP_TIMEOUT_SECONDS,
    SEC_COMPANY_FACTS_URL,
    SEC_SUBMISSIONS_URL,
    SEC_TICKER_MAP_URL,
    TAVILY_EXTRACT_URL,
    TAVILY_SEARCH_URL,
    exa_api_key,
    sec_user_agent,
    tavily_api_key,
)


def tavily_search(
    query: str,
    max_results: int = 5,
    include_answer: bool = False,
    include_raw_content: bool = False,
    end_date: str | None = None,
) -> dict[str, Any]:
    """Call Tavily's /search endpoint. Raises if TAVILY_API_KEY is not set.

    include_answer defaults False: this project needs primary source material, not
    another model's synthesized answer. include_raw_content defaults False too --
    full content comes from the separate, explicit tavily_extract() call on
    selected URLs, not implicitly bundled into every search hit.

    end_date (YYYY-MM-DD), when given, is passed as Tavily's documented server-side
    publish-date filter -- per Tavily's own API reference, results published after
    it should never be returned. DOCUMENTED LIMITATION, confirmed by live testing on
    2026-08-26: this is NOT reliably enforced in practice on this account, for
    either topic="general" (what build_official_source_queries uses) or
    topic="news" -- identical result sets were returned with and without end_date
    set, including hits with published_date years past the cutoff. Most
    "general"-topic hits also carry no published_date at all, so the client-side
    post-filter in cli.cmd_prepare (the actual causality backstop) can't check them
    either. Sent anyway (harmless, spec-correct, may start working on a different
    plan/topic/Tavily version) but do not treat it as a reliable guarantee -- see
    README.md "Known limitations" and web-search-usage.md for the full account.
    """
    api_key = tavily_api_key()
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY is not set; cannot perform Tavily search")
    payload = {
        "api_key": api_key,
        "query": query,
        "max_results": max_results,
        "include_answer": include_answer,
        "include_raw_content": include_raw_content,
    }
    if end_date:
        payload["end_date"] = end_date
    with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as client:
        resp = client.post(TAVILY_SEARCH_URL, json=payload)
        resp.raise_for_status()
        return resp.json()


# Generic official-document types to search for. No industry terms -- if a company's
# own materials name a sector-specific document, the agent adds that separately; this
# function never guesses sector vocabulary.
_OFFICIAL_DOC_TYPES = (
    "earnings release",
    "earnings call transcript",
    "investor presentation",
    "outlook guidance",
    "regulatory filing",
    "previous earnings call",
    "previous guidance",
)


def build_official_source_queries(company_name: str, ticker: str, event_date: str) -> list[str]:
    """Build narrow, official-source-only Tavily queries from the company name,
    ticker, event date and the generic document types above. No sector keywords are
    injected -- the caller (agent) may extend this list with terms it discovered in
    the company's own disclosures, but this function itself stays domain-agnostic.
    """
    return [f"{company_name} {ticker} {event_date} {doc_type}" for doc_type in _OFFICIAL_DOC_TYPES]


def tavily_extract(url: str, extract_depth: str = "basic") -> dict[str, Any]:
    """Call Tavily's /extract endpoint for a known URL -- returns full page content
    (markdown/text), unlike a search hit's short snippet. This is what makes a
    source quote-checkable; see models.WebEvidence and cli.cmd_prepare's extraction
    step.
    """
    api_key = tavily_api_key()
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY is not set; cannot perform Tavily extract")
    payload = {"api_key": api_key, "urls": [url], "extract_depth": extract_depth}
    with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as client:
        resp = client.post(TAVILY_EXTRACT_URL, json=payload)
        resp.raise_for_status()
        return resp.json()


def exa_search(
    query: str, num_results: int = 5, search_type: str = "auto", end_published_date: str | None = None
) -> dict[str, Any]:
    """Call Exa's /search endpoint. Raises if EXA_API_KEY is not set.

    end_published_date (ISO 8601), when given, is Exa's documented server-side
    publish-date filter. Same DOCUMENTED LIMITATION as tavily_search's end_date:
    confirmed by live testing on 2026-08-26 to not reliably exclude post-cutoff
    results -- sent anyway, but the real causality guard is cli.cmd_prepare's
    client-side published_date check.
    """
    api_key = exa_api_key()
    if not api_key:
        raise RuntimeError("EXA_API_KEY is not set; cannot perform Exa search")
    payload = {"query": query, "type": search_type, "numResults": num_results}
    if end_published_date:
        payload["endPublishedDate"] = end_published_date
    headers = {"x-api-key": api_key, "Content-Type": "application/json"}
    with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as client:
        resp = client.post(EXA_SEARCH_URL, headers=headers, json=payload)
        resp.raise_for_status()
        return resp.json()


def exa_contents(url: str) -> dict[str, Any]:
    """Call Exa's /contents endpoint for a known URL -- returns full page text,
    confirmed live (2026-08-26). Mirrors tavily_extract(url)'s signature/purpose.
    """
    api_key = exa_api_key()
    if not api_key:
        raise RuntimeError("EXA_API_KEY is not set; cannot perform Exa contents fetch")
    payload = {"urls": [url], "text": True}
    headers = {"x-api-key": api_key, "Content-Type": "application/json"}
    with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as client:
        resp = client.post(EXA_CONTENTS_URL, headers=headers, json=payload)
        resp.raise_for_status()
        return resp.json()


def _normalize_hits(raw_results: list[dict[str, Any]], provider: str) -> list[dict[str, Any]]:
    """Map either provider's raw search-hit shape to one canonical shape so
    cli.cmd_prepare never branches on provider: {url, title, score, published_date}.
    """
    if provider == "exa":
        return [
            {
                "url": r.get("url"),
                "title": r.get("title"),
                "score": r.get("score", 0),
                "published_date": r.get("publishedDate"),
            }
            for r in raw_results
        ]
    return [
        {
            "url": r.get("url"),
            "title": r.get("title"),
            "score": r.get("score", 0),
            "published_date": r.get("published_date"),
        }
        for r in raw_results
    ]


def web_search(query: str, provider: str, max_results: int, end_date: str | None = None) -> list[dict[str, Any]]:
    """Provider-agnostic search dispatch, returning normalized hits (see
    _normalize_hits). `provider` is config.RESEARCH_WEB_SEARCH_PROVIDER ("exa" or
    "tavily"); end_date is YYYY-MM-DD, converted to Exa's ISO 8601 shape internally.
    """
    if provider == "exa":
        from .config import EXA_TYPE

        end_published_date = f"{end_date}T23:59:59.000Z" if end_date else None
        result = exa_search(query, num_results=max_results, search_type=EXA_TYPE, end_published_date=end_published_date)
    else:
        from .config import TAVILY_INCLUDE_ANSWER, TAVILY_INCLUDE_RAW_CONTENT

        result = tavily_search(
            query,
            max_results=max_results,
            include_answer=TAVILY_INCLUDE_ANSWER,
            include_raw_content=TAVILY_INCLUDE_RAW_CONTENT,
            end_date=end_date,
        )
    return _normalize_hits(result.get("results", []), provider)


def web_extract(url: str, provider: str) -> str | None:
    """Provider-agnostic content-extraction dispatch -- returns full text or None."""
    if provider == "exa":
        result = exa_contents(url)
    else:
        from .config import TAVILY_EXTRACT_DEPTH

        result = tavily_extract(url, extract_depth=TAVILY_EXTRACT_DEPTH)
    results = result.get("results", [])
    if not results:
        return None
    return results[0].get("text") if provider == "exa" else results[0].get("raw_content")


def _sec_headers() -> dict[str, str]:
    return {"User-Agent": sec_user_agent(), "Accept": "application/json"}


def resolve_cik(ticker: str) -> str | None:
    """Look up a company's zero-padded CIK from SEC's ticker-to-CIK map."""
    with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS, headers=_sec_headers()) as client:
        resp = client.get(SEC_TICKER_MAP_URL)
        resp.raise_for_status()
        data = resp.json()
    ticker_upper = ticker.upper()
    for row in data.values():
        if row.get("ticker", "").upper() == ticker_upper:
            return f"{int(row['cik_str']):010d}"
    return None


def get_submissions(cik: int) -> dict[str, Any]:
    url = SEC_SUBMISSIONS_URL.format(cik=cik)
    with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS, headers=_sec_headers()) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.json()


def get_company_facts(cik: int) -> dict[str, Any]:
    url = SEC_COMPANY_FACTS_URL.format(cik=cik)
    with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS, headers=_sec_headers()) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.json()


def extract_financials_from_company_facts(
    company_facts: dict[str, Any], concepts: list[str], period_end: str | None = None
) -> dict[str, Any]:
    """Pull one value per requested us-gaap concept.

    `concepts` are us-gaap XBRL tags, e.g. "Revenues", "NetIncomeLoss",
    "EarningsPerShareDiluted". Checks every unit type under the concept (not just
    "USD"), since per-share concepts like diluted EPS are tagged "USD-per-shares" --
    restricting to "USD" silently drops them.

    If `period_end` (an XBRL "end" date, e.g. "2026-06-30") is given, only facts for
    that exact period are considered -- this pins the fact to the earnings event
    instead of picking whatever period happens to be latest, which could be a later
    quarter, an annual figure, or a restatement. Without it, the latest-by-end fact is
    used (documented limitation, not a default to rely on for a real pilot).

    Returns {concept: {"value", "end", "unit", "form", "fy", "filed", "accn"}} so the
    selected fact's provenance is preserved for audit, not just its value.
    """
    facts = company_facts.get("facts", {}).get("us-gaap", {})
    out: dict[str, Any] = {}
    for concept in concepts:
        units_by_type = facts.get(concept, {}).get("units", {})
        candidates = [
            (unit_type, entry) for unit_type, entries in units_by_type.items() for entry in entries
        ]
        if period_end:
            candidates = [(u, e) for u, e in candidates if e.get("end") == period_end]
        if not candidates:
            continue
        unit_type, latest = max(candidates, key=lambda ue: ue[1].get("end", ""))
        out[concept] = {
            "value": latest.get("val"),
            "end": latest.get("end"),
            "unit": unit_type,
            "form": latest.get("form"),
            "fy": latest.get("fy"),
            "filed": latest.get("filed"),
            "accn": latest.get("accn"),
        }
    return out
