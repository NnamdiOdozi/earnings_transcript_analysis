from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from . import config
from .ingest import load_transcript
from .models import Manifest, SourceRecord, WebEvidence
from .paths import CURRENT_LAYOUT, RunPaths
from .process import (
    sanitize,
    scan_for_injection,
    segment_transcript_with_report,
    sha256_hex,
)
from .research import (
    _classify_temporal_status,
    _filter_post_event,
    _parse_event_cutoff,
    _select_round_robin,
)
from .runio import _append_processing_log, _now_iso, _write_json


def _archive_existing_run(run_dir: Path) -> None:
    """If run_dir already holds a manifest.json (a prior `prepare` ran here), move its
    entire contents under run_dir/_archive/<timestamp>/ before writing fresh output --
    a rerun for the same ticker/event must never silently overwrite prior evidence.
    """
    paths = RunPaths.at(run_dir)
    if not (paths.manifest).exists():
        return
    stamp = _now_iso().replace(":", "").rstrip("Z")
    dest = paths.archive / stamp
    dest.mkdir(parents=True, exist_ok=True)
    for item in run_dir.iterdir():
        if item.name == config.ARCHIVE_SUBDIR:
            continue
        shutil.move(str(item), str(dest / item.name))


def cmd_discover_peers(args: argparse.Namespace) -> int:
    """Discover the company's analyst-recognised peer group by web search, so the agent
    can pick ~4 comparables to pass to `prepare --peers`. The SEARCH is deterministic
    and archived (hashed) here; the SELECTION of which 4 are the agreed peers is the
    agent's judgment, made by reading the extracted candidate pages. Output lives under
    runs/<TICKER>/peer-discovery/ -- company-level, not per-event (a company's peers
    don't change between quarters), so `prepare`'s per-event archiving never touches it.
    """
    if not config.RESEARCH_WEB_SEARCH_ENABLED:
        print("Web search is disabled (config.toml [research] web_search_enabled); cannot discover peers.")
        return 1
    from .sources import build_peer_group_queries, web_extract, web_search

    provider = config.RESEARCH_WEB_SEARCH_PROVIDER
    company_name = args.company_name or args.ticker
    out_dir = config.RUNS_DIR / args.ticker.upper() / "peer-discovery"
    # Archive any prior discovery FIRST. Without this a shorter rerun (fewer candidates)
    # leaves stale candidate-NN.md from the old run on disk, and the agent globs
    # candidate-*.md -- so it could read a superseded candidate as a current one.
    _archive_existing_run(out_dir)
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    max_results = config.EXA_NUM_RESULTS if provider == "exa" else config.TAVILY_MAX_RESULTS
    max_extracted = config.EXA_MAX_EXTRACTED_SOURCES if provider == "exa" else config.TAVILY_MAX_EXTRACTED_SOURCES

    # Peer-group membership is not event-relative, but the user still wants an optional
    # cutoff as a safety net (a peer list published after the event can't have informed
    # the call). --event-date is optional here; when given, dated post-event hits are
    # dropped from extraction and undated ones pass through, same as prepare.
    event_cutoff = _parse_event_cutoff(getattr(args, "event_date", None))
    provider_end_date = event_cutoff.isoformat() if event_cutoff else None

    queries = build_peer_group_queries(company_name, args.ticker, config.RESEARCH_PEER_GROUP_QUERIES)
    sources: list[SourceRecord] = []
    all_hits: list[dict] = []
    for qi, query in enumerate(queries, start=1):
        hits = web_search(query, provider=provider, max_results=max_results, end_date=provider_end_date)
        for hit in hits:
            hit["_class"] = "peer_group"  # tag for the shared selection helper below
            hit["_temporal_status"] = _classify_temporal_status(hit.get("published_date"), event_cutoff)
        all_hits.extend(hits)
        for hi, hit in enumerate(hits, start=1):
            retrieved_at = _now_iso()
            hit_bytes = json.dumps(
                {**hit, "_provider": provider, "_query": query, "_class": "peer_group", "_retrieved_at": retrieved_at},
                indent=2,
            ).encode("utf-8")
            hit_path = raw_dir / f"query-{qi:02d}-hit-{hi:02d}.json"
            hit_path.write_bytes(hit_bytes)
            sources.append(
                SourceRecord(
                    path=str(hit_path.relative_to(out_dir)),
                    origin=hit.get("url", query),
                    retrieved_at=retrieved_at,
                    content_type="application/json",
                    sha256=sha256_hex(hit_bytes),
                    byte_length=len(hit_bytes),
                )
            )

    # Apply the causality guard (drops dated post-event hits, keeps undated) then extract
    # the top few unique pages so the agent reads the actual peer lists, not snippets.
    causal_hits, excluded_future = _filter_post_event(all_hits, event_cutoff)
    selected = _select_round_robin(causal_hits, max_extracted)

    candidate_paths: list[str] = []
    for ci, hit in enumerate(selected, start=1):
        url = hit["url"]
        try:
            content = web_extract(url, provider=provider)
        except Exception:  # noqa: BLE001 -- skip a failed page, never fabricate content
            content = None
        if not content:
            continue
        content_bytes = content.encode("utf-8")
        cand_path = out_dir / f"candidate-{ci:02d}.md"
        cand_path.write_text(content, encoding="utf-8")
        candidate_paths.append(str(cand_path))
        sources.append(
            SourceRecord(
                path=str(cand_path.relative_to(out_dir)),
                origin=url,
                retrieved_at=_now_iso(),
                content_type="text/markdown",
                sha256=sha256_hex(content_bytes),
                byte_length=len(content_bytes),
            )
        )

    manifest = Manifest(
        ticker=args.ticker.upper(),
        event_id="peer-discovery",
        created_at=_now_iso(),
        sources=sources,
        queries=queries,
        notes=[
            f"Peer-group discovery via {provider}: {len(all_hits)} hit(s) from {len(queries)} queries.",
            f"Extracted {len(candidate_paths)} candidate page(s) for the agent to read and pick ~4 peers.",
        ]
        + (
            [
                f"Excluded {excluded_future} {provider} hit(s) published after the event "
                f"date ({args.event_date}) from extraction (causality guard)."
            ]
            if excluded_future
            else []
        ),
    )
    _write_json(out_dir / config.MANIFEST_FILENAME, manifest.model_dump())

    print(f"Peer-group discovery for {args.ticker.upper()} -> {out_dir}")
    print(f"  {len(queries)} queries, {len(all_hits)} hits, {len(candidate_paths)} extracted page(s).")
    if candidate_paths:
        print("  Read these, pick ~4 analyst-agreed comparables, then run `prepare --peers ...`:")
        for path in candidate_paths:
            print(f"    - {path}")
    else:
        print("  No pages extracted -- widen config [research] peer_group_queries or check the provider.")
    return 0


def cmd_prepare(args: argparse.Namespace) -> int:
    run_dir = config.run_dir(args.ticker, args.event_id)
    # State the layout rather than detect it: this run's manifest does not exist yet, and
    # a prior run's manifest may still be sitting here declaring the OLD layout until
    # _archive_existing_run moves it. Every run prepared from now on is CURRENT_LAYOUT.
    paths = RunPaths.at(run_dir, CURRENT_LAYOUT)
    _archive_existing_run(run_dir)
    raw_dir = paths.raw
    normalized_dir = paths.normalized
    evidence_dir = paths.evidence
    for d in (raw_dir, normalized_dir, evidence_dir, *paths.stage_dirs):
        d.mkdir(parents=True, exist_ok=True)

    loaded = load_transcript(args.transcript)

    pdf_source_record = None
    pdf_reformat_note = None
    if loaded.raw_bytes is not None:
        from .reformat import looks_like_factset_format, reformat_factset_transcript

        pdf_raw_path = raw_dir / f"transcript{loaded.raw_suffix}"
        pdf_raw_path.write_bytes(loaded.raw_bytes)
        pdf_source_record = SourceRecord(
            path=str(pdf_raw_path.relative_to(run_dir)),
            origin=loaded.origin,
            retrieved_at=_now_iso(),
            content_type="application/pdf",
            sha256=sha256_hex(loaded.raw_bytes),
            byte_length=len(loaded.raw_bytes),
        )
        if config.PDF_FACTSET_REFORMAT_ENABLED and looks_like_factset_format(
            loaded.raw_text, config.PDF_FACTSET_SEPARATOR_PATTERN
        ):
            loaded.raw_text = reformat_factset_transcript(
                loaded.raw_text, config.PDF_FACTSET_SEPARATOR_PATTERN, config.PDF_FACTSET_BANNER_PATTERNS
            )
            pdf_reformat_note = "PDF source: FactSet-style layout detected and reformatted."
        else:
            pdf_reformat_note = "PDF source: no known vendor layout auto-detected; segmented as-is."

    raw_bytes = loaded.raw_text.encode("utf-8")
    if loaded.is_html:
        raw_filename = "transcript.html"
    elif loaded.raw_bytes is not None:
        raw_filename = "transcript.converted.md"
    else:
        raw_filename = "transcript.txt"
    raw_path = raw_dir / raw_filename
    raw_path.write_text(loaded.raw_text, encoding="utf-8")  # archive raw, verbatim, before sanitisation
    _append_processing_log(args.ticker, args.event_id, loaded, raw_bytes, run_dir)

    sanitized = sanitize(loaded.raw_text, is_html=loaded.is_html)
    segmentation = segment_transcript_with_report(sanitized)
    segments = segmentation.segments
    if loaded.raw_bytes is not None and not any(seg.speaker for seg in segments):
        raise ValueError(
            "PDF ingestion produced zero recognised speaker turns after segmentation -- "
            "refusing to proceed with an unattributed transcript. This PDF's vendor "
            "layout is not one we've handled before; if it is FactSet-style, check "
            "config.toml [pdf_ingestion] patterns; otherwise this vendor needs its own "
            "reformatter. See docs/AUDITABILITY.md 'Known limitations'."
        )
    transcript_path = normalized_dir / config.TRANSCRIPT_FILENAME
    with transcript_path.open("w", encoding="utf-8") as fh:
        for seg in segments:
            fh.write(seg.model_dump_json() + "\n")
    _write_json(
        paths.segmentation_report,
        {
            "created_at": _now_iso(),
            "sanitized_input_sha256": sha256_hex(sanitized.encode("utf-8")),
            "segment_count": len(segments),
            "omission_count": len(segmentation.omissions),
            "omissions": segmentation.omissions,
            # Advisory only -- lines that looked speaker-shaped but didn't parse as
            # one (see process._looks_speaker_shaped). Never blocks the run; exists
            # so a missed speaker surfaces as data instead of requiring another
            # accidental discovery (confirmed live, regex audit, 2026-09-04).
            "near_miss_speaker_count": len(segmentation.near_miss_speakers),
            "near_miss_speakers": segmentation.near_miss_speakers,
        },
    )

    # Best-effort prompt-injection FLAG over the sanitised transcript (config-gated).
    # Advisory only -- it records matches, never blocks the run or removes text. Runs
    # AFTER sanitize so invisible-char evasions are already normalised away. Transcript
    # only, not Exa/Tavily results (those providers run their own defences).
    injection_findings: list[dict] = []
    if config.SANITISATION_INJECTION_SCAN_ENABLED:
        injection_findings = scan_for_injection(sanitized, config.SANITISATION_INJECTION_PATTERNS)
        _write_json(
            paths.injection_scan,
            {
                "scanned_at": _now_iso(),
                "pattern_count": len(config.SANITISATION_INJECTION_PATTERNS),
                "finding_count": len(injection_findings),
                "findings": injection_findings,
            },
        )
    if not config.SANITISATION_INJECTION_SCAN_ENABLED:
        injection_note = "Prompt-injection scan: disabled (config.toml [sanitisation])."
    elif injection_findings:
        injection_note = (
            f"Prompt-injection scan: {len(injection_findings)} suspicious phrase(s) flagged in "
            f"transcript -- advisory only, run not blocked. See injection-scan.json."
        )
    else:
        injection_note = "Prompt-injection scan: clean (no configured patterns matched)."

    financials: dict = {}
    sec_status = "disabled"
    cik = args.sec_cik
    if config.RESEARCH_SEC_ENABLED:
        if not cik and config.SEC_RESOLVE_CIK_FROM_TICKER:
            from .sources import resolve_cik

            cik = resolve_cik(args.ticker)
        if cik:
            from .sources import (
                extract_financials_from_company_facts,
                get_company_facts,
            )

            facts = get_company_facts(int(cik))
            financials = extract_financials_from_company_facts(
                facts,
                concepts=config.SEC_CONCEPTS,
                period_end=args.sec_period_end,
                period_type=args.sec_period_type,
                require_period_type_match=config.SEC_REQUIRE_PERIOD_MATCH,
            )
            sec_status = "ok"
        else:
            # Not every registrant is discoverable by ticker (e.g. non-SEC-registered
            # foreign private issuers); this is a normal, expected outcome, not an
            # error -- the pipeline continues with whatever other evidence exists.
            sec_status = "not_applicable"
    financials_path = evidence_dir / config.FINANCIALS_FILENAME
    _write_json(financials_path, financials)

    provider = config.RESEARCH_WEB_SEARCH_PROVIDER  # "exa" (default) | "tavily"
    web_search_sources: list[SourceRecord] = []
    web_search_status = "disabled"
    web_evidence: list[WebEvidence] = []
    web_evidence_sources: list[SourceRecord] = []
    web_evidence_notes: list[str] = []
    queries: list[str] = []
    if config.RESEARCH_WEB_SEARCH_ENABLED:
        from .sources import (
            build_consensus_queries,
            build_peer_queries,
            web_extract,
            web_search,
        )

        max_results = config.EXA_NUM_RESULTS if provider == "exa" else config.TAVILY_MAX_RESULTS
        max_extracted = config.EXA_MAX_EXTRACTED_SOURCES if provider == "exa" else config.TAVILY_MAX_EXTRACTED_SOURCES

        web_search_raw_dir = raw_dir / "web"
        web_search_raw_dir.mkdir(parents=True, exist_ok=True)
        company_name = args.company_name or args.ticker
        event_date = args.event_date or args.event_id
        # Repurposed queries: consensus/expectations + peer-group results (info NOT in
        # the transcript), replacing the old official-document queries that restated the
        # call. Each query is tagged with its class so the raw archive records what a hit
        # was looking for. Peers come from --peers (agent-supplied from the transcript);
        # with none, only the consensus queries run.
        # Each tuple is (archive_class, query, select_key). archive_class is the coarse
        # "consensus"/"peer" label stamped into the raw hit for provenance. select_key is
        # the FINER bucket the extraction round-robin interleaves on: consensus is one
        # bucket, but each peer is its own (peer:<name>) so one high-scoring peer can't
        # fill every peer slot and starve the other three -- the peer group's whole point
        # is 4-way competitive breadth.
        classified_queries = [
            ("consensus", q, "consensus")
            for q in build_consensus_queries(company_name, args.ticker, args.event_id, config.RESEARCH_CONSENSUS_QUERIES)
        ]
        for peer in args.peers:
            classified_queries += [
                ("peer", q, f"peer:{peer}")
                for q in build_peer_queries(
                    company_name, args.ticker, args.event_id, [peer], config.RESEARCH_PEER_QUERIES
                )
            ]
        queries = [q for _, q, _ in classified_queries]

        # Causality guard, attempted server-side: pass event_date to the active
        # provider's own publish-date filter. DOCUMENTED LIMITATION, confirmed by
        # live testing on 2026-08-26 for both Tavily and Exa: not reliably enforced
        # in practice -- see sources.web_search's callees' docstrings. Sent anyway
        # (harmless); the real guard is the client-side filter below. Only set when
        # --event-date parses as a real calendar date (it defaults to event_id,
        # e.g. "2026-q2", which isn't one).
        event_cutoff = _parse_event_cutoff(event_date)
        provider_end_date = event_cutoff.isoformat() if event_cutoff else None

        all_hits: list[dict] = []  # every normalized hit seen, for the extract-selection step below
        for qi, (qclass, query, select_key) in enumerate(classified_queries, start=1):
            hits = web_search(query, provider=provider, max_results=max_results, end_date=provider_end_date)
            for hit in hits:
                hit["_class"] = qclass  # coarse label written to the raw archive (provenance)
                hit["_select_key"] = select_key  # finer bucket the round-robin interleaves on
                hit["_temporal_status"] = _classify_temporal_status(hit.get("published_date"), event_cutoff)
            all_hits.extend(hits)
            # archive_all_sources controls how many hits per query we keep -- the
            # config default (true) matches "narrow queries, but don't discard what
            # the provider returns for them" rather than us silently dropping evidence.
            kept = hits if config.RESEARCH_ARCHIVE_ALL_SOURCES else hits[:1]
            for hi, hit in enumerate(kept, start=1):
                # Stamped into the archived file itself (not just manifest.json's
                # per-source retrieved_at) so the fetch time is visible without
                # cross-referencing the manifest.
                hit_retrieved_at = _now_iso()
                # "_query" records the exact search string that produced this hit --
                # previously only recoverable by re-reading the query builder in
                # sources.py and assuming its fixed template never changed. "_provider" records
                # which search API (exa/tavily) produced it -- previously not recorded
                # ANYWHERE per-hit: the archive directory is always literally named
                # "web" regardless of provider (see web_search_raw_dir above), not
                # "exa"/"tavily", so only manifest.json's free-text notes said which
                # provider ran, and only once for the whole run, not per file.
                hit_bytes = json.dumps(
                    {
                        **hit,
                        "_provider": provider,
                        "_query": query,
                        "_class": qclass,  # "consensus" | "peer" -- what this query was looking for
                        "_retrieved_at": hit_retrieved_at,
                    },
                    indent=2,
                ).encode("utf-8")
                hit_filename = f"query-{qi:02d}-hit-{hi:02d}.json"
                (web_search_raw_dir / hit_filename).write_bytes(hit_bytes)
                web_search_sources.append(
                    SourceRecord(
                        path=str((web_search_raw_dir / hit_filename).relative_to(run_dir)),
                        origin=hit.get("url", query),
                        retrieved_at=hit_retrieved_at,
                        content_type="application/json",
                        sha256=sha256_hex(hit_bytes),
                        byte_length=len(hit_bytes),
                    )
                )
        web_search_status = (
            f"ok ({len(web_search_sources)} hit(s) from {len(queries)} queries)" if web_search_sources else "no_results"
        )

        # Search hits are short snippets, not quote-checkable evidence -- a claim
        # can't cite one. Extract full content for the best few so they become real,
        # citable WebEvidence (see models.WebEvidence, validate.check_evidence_reference).
        if all_hits:
            web_dir = evidence_dir / config.WEB_SUBDIR
            web_dir.mkdir(parents=True, exist_ok=True)

            # Causality guard, actual enforcement: provider_end_date above is not
            # reliably honored (confirmed by live testing on both providers), so this
            # client-side check on published_date is the real guard, not a backstop.
            # It only catches hits that carry a published_date at all -- confirmed by
            # the same testing that most hits do not, so this guard's real-world
            # coverage is narrower than it looks. Undated hits are kept, not dropped.
            causal_hits, excluded_future = _filter_post_event(all_hits, event_cutoff)
            if excluded_future:
                web_evidence_notes.append(
                    f"Excluded {excluded_future} {provider} hit(s) published after the event "
                    f"date ({event_date}) from citable evidence (causality guard)."
                )

            # Round-robin across query classes so consensus (run first, more hits) can't
            # fill every extraction slot and starve peer results -- the live bug this
            # fixes. Within a class, provider relevance order is preserved (see helper).
            selected = _select_round_robin(causal_hits, max_extracted)
            for wi, hit in enumerate(selected, start=1):
                url = hit["url"]
                try:
                    raw_content = web_extract(url, provider=provider)
                except Exception as exc:  # noqa: BLE001 -- record and continue, never fabricate content
                    raw_content = None
                    web_evidence_notes.append(f"web evidence extraction failed for {url}: {exc}")
                    continue
                if not raw_content:
                    web_evidence_notes.append(f"web evidence extraction returned no content for {url}")
                    continue
                web_id = f"web-{wi:03d}"
                content_bytes = raw_content.encode("utf-8")
                content_filename = f"{web_id}.md"
                content_path = web_dir / content_filename
                content_path.write_text(raw_content, encoding="utf-8")
                web_evidence.append(
                    WebEvidence(
                        id=web_id,
                        url=url,
                        title=hit.get("title"),
                        publisher=None,
                        published_at=hit.get("published_date"),
                        temporal_status=hit.get("_temporal_status", "unchecked"),
                        retrieved_at=_now_iso(),
                        content_path=str(content_path.relative_to(run_dir)),
                        content_sha256=sha256_hex(content_bytes),
                    )
                )
                web_evidence_sources.append(
                    SourceRecord(
                        path=str(content_path.relative_to(run_dir)),
                        origin=url,
                        retrieved_at=_now_iso(),
                        content_type="text/markdown",
                        sha256=sha256_hex(content_bytes),
                        byte_length=len(content_bytes),
                    )
                )
            if web_evidence:
                web_evidence_path = evidence_dir / config.WEB_EVIDENCE_FILENAME
                with web_evidence_path.open("w", encoding="utf-8") as fh:
                    for we in web_evidence:
                        fh.write(we.model_dump_json() + "\n")

    manifest = Manifest(
        ticker=args.ticker.upper(),
        event_id=args.event_id,
        created_at=_now_iso(),
        layout_version=paths.layout,
        event_date=getattr(args, "event_date", None),
        sources=(
            ([pdf_source_record] if pdf_source_record else [])
            + [
                SourceRecord(
                    path=str(raw_path.relative_to(run_dir)),
                    origin=loaded.origin,
                    retrieved_at=_now_iso(),
                    content_type=loaded.content_type,
                    sha256=sha256_hex(raw_bytes),
                    byte_length=len(raw_bytes),
                )
            ]
            + web_search_sources
            + web_evidence_sources
        ),
        queries=queries,
        notes=[
            "Raw source archived verbatim before sanitisation.",
            (
                f"Segmentation: {len(segmentation.omissions)} structural omission(s) recorded in "
                f"{config.SEGMENTATION_REPORT_FILENAME}."
            ),
            (
                f"Segmentation: {len(segmentation.near_miss_speakers)} near-miss speaker-shaped "
                f"line(s) advisory-flagged in {config.SEGMENTATION_REPORT_FILENAME} -- worth a "
                "look if any real speaker turns seem to be missing."
                if segmentation.near_miss_speakers
                else "Segmentation: no near-miss speaker-shaped lines flagged."
            ),
            injection_note,
            f"SEC evidence: {sec_status}" + (f" (CIK {cik})" if sec_status == "ok" else ""),
            f"Web search evidence ({provider}): {web_search_status}",
            f"Web evidence (extracted, citable): {len(web_evidence)} source(s)",
        ]
        + ([pdf_reformat_note] if pdf_reformat_note else [])
        + web_evidence_notes,
    )
    _write_json(paths.manifest, manifest.model_dump())

    print(f"Prepared source pack at {run_dir} ({len(segments)} segments).")
    return 0
