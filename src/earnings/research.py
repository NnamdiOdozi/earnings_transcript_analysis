from __future__ import annotations

from datetime import date

from .models import TemporalStatus


def _parse_event_cutoff(event_date: str | None):
    """Parse a --event-date string into a datetime.date, or None if it isn't a real
    calendar date (event_id like "2026-q2" is the common non-date default). Shared by
    prepare and discover-peers so both apply the causality guard identically."""
    if not event_date:
        return None
    try:
        return date.fromisoformat(event_date[:10])
    except (ValueError, TypeError):
        return None


def _filter_post_event(hits: list[dict], event_cutoff) -> tuple[list[dict], int]:
    """Drop hits whose published_date is AFTER event_cutoff -- a source that appeared
    after the call could not have informed it, so it must never become citable evidence.
    Hits with no parseable published_date are KEPT, not dropped (undated post-event
    slippage is a consciously-accepted residual risk -- see README known limitations).
    Returns (kept_hits, excluded_count). With no cutoff, keeps everything."""
    kept: list[dict] = []
    excluded = 0
    for hit in hits:
        temporal_status = _classify_temporal_status(hit.get("published_date"), event_cutoff)
        hit["_temporal_status"] = temporal_status
        if temporal_status == "post_event":
            excluded += 1
            continue
        kept.append(hit)
    return kept, excluded


def _classify_temporal_status(published_date: str | None, event_cutoff) -> TemporalStatus:
    """Classify provider publication metadata without interpreting page content.

    Day granularity only: a hit published ON the event date compares as not-after the
    cutoff and so is labelled "pre_event", even when it was published after the results
    dropped. "pre_event" therefore means "not dated after the event", never "known to
    predate the call" -- see web-search-usage.md's causality guard section.
    """
    if not event_cutoff:
        return "unchecked"
    if not published_date:
        return "undated"
    try:
        parsed_date = date.fromisoformat(published_date[:10])
    except (ValueError, TypeError):
        return "undated"
    return "post_event" if parsed_date > event_cutoff else "pre_event"


def _select_round_robin(hits: list[dict], max_extracted: int) -> list[dict]:
    """Pick up to max_extracted unique-URL hits, INTERLEAVED across their bucket so no
    single bucket fills every extraction slot. This fixes the live bug where consensus
    queries (run first, more hits) crowded out every peer result -- 0 of 10 extracted
    pages were peer-related -- AND the narrower one where one peer crowded out the other
    three. The bucket is `_select_key` (consensus is one bucket; each peer is its own,
    peer:<name>), falling back to the coarse `_class` when no finer key is set (e.g.
    discover-peers, where everything is one class). Within a bucket the provider's own
    relevance order is kept (score desc; unscored providers like Exa "auto" fall back to
    result order via a stable sort). URLs are deduped globally across buckets."""
    ordered = sorted(
        hits, key=lambda h: h.get("score") if h.get("score") is not None else -1, reverse=True
    )
    by_class: dict[str, list[dict]] = {}
    for hit in ordered:
        by_class.setdefault(hit.get("_select_key") or hit.get("_class", ""), []).append(hit)

    queues = list(by_class.values())
    idxs = [0] * len(queues)
    seen_urls: set[str] = set()
    selected: list[dict] = []
    while len(selected) < max_extracted:
        progressed = False
        for i, queue in enumerate(queues):
            if idxs[i] >= len(queue):
                continue
            hit = queue[idxs[i]]
            idxs[i] += 1
            progressed = True
            url = hit.get("url")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            selected.append(hit)
            if len(selected) >= max_extracted:
                break
        if not progressed:  # every class queue exhausted
            break
    return selected
