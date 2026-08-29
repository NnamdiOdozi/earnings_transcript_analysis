# Review Report: MSFT — 2026-q4

**Verdict:** pass
**Reviewed at (agent-reported):** 2026-08-27T15:20:00Z (model: opus)
**Checked at (system clock):** 2026-08-27T15:00:48Z

## Summary
Pass. The MSFT 2026-q4 run is well-supported and internally consistent. Deterministic upstream checks passed (validation.json.ok and outlook-validation.json.ok both true; manifest hashed; 44 claims all with valid ids; brief citations all resolve). Source spot-checks confirm the transcript and the four cited peer/consensus web files are genuine and correctly periodized, and temporal integrity holds (Apple's post-call June quarter correctly excluded after reading the release content, not trusting metadata). Claim characterizations are fair in full context, period labels are unambiguous, signs/units/periods are used correctly, and no cross-sector template language leaked into the prose. Two low-severity notes only: a stray 2010 half-year revenue fact sits unused in financials.json, and the brief's Q4 EPS beat could note the ~\$0.27 discrete-item benefit embedded in the adjusted \$4.74 (the beat survives regardless). No high/critical issues; the run can proceed.

## Source checks
- **[info]** normalized/transcript.jsonl: 'Microsoft Fiscal Year 2026 Fourth Quarter Earnings Conference Call ... Wednesday, July 29, 2026 Satya Nadella ... and Amy Hood'
  - Evidence: The archived transcript is the genuine MSFT FY2026 Q4 call (29 Jul 2026). Prepared remarks (seg-0003 Nadella, seg-0004 Hood) and Q&A (seg-0006..seg-0034) are coherent and every quoted claim substring is present in the cited segment.
  - Recommendation: None.
- **[info]** evidence/web/web-002.md: 'Google Cloud saw a continued increase in customer demand as revenues increased 48% to \\$17.7 billion'
  - Evidence: Content is the real Alphabet Q4/FY2025 release (quarter ended December 31, 2025), matching claim-041 quote and its stated period '3 months to 31 Dec 2025'. web-003 (Amazon, 'AWS segment sales increased 24% year-over-year to \$35.6 billion', Q4 Dec-2025) and web-004 (Oracle, 'Record Q4 Total Cloud Revenues \$9.9 billion, up 47% USD', quarter ended 31 May 2026) likewise match claim-039/claim-040 verbatim and by period.
  - Recommendation: None.
- **[info]** evidence/web/web-006.md: 'Wall Street expects Microsoft Corporation to report earnings of \\$4.24 per share on revenue of \\$87.67B'
  - Evidence: Genuine AlphaStreet MSFT Q4 FY2026 preview, published_at 2026-07-26 (before the 29 Jul call), so valid as a pre-print consensus anchor for claim-038/claim-043. Consensus figures (\$4.24 EPS / \$87.67B) match the claim exactly.
  - Recommendation: None.
- **[info]** evidence/web/web-005.md: 'Apple will provide live streaming of its Q3 2026 financial results conference call beginning at 2:00 p.m. PT on July 30, 2026'
  - Evidence: Read the Apple release content directly (not just metadata): it confirms Apple's June-quarter results were released 30 Jul 2026, one day AFTER the MSFT call. web-005 is correctly NOT cited by any claim, matching the brief's temporal-integrity exclusion of Apple. Note web-evidence.jsonl lists web-005 published_at as 2026-07-01, which is unreliable metadata contradicted by the content itself.
  - Recommendation: None.
- **[low]** evidence/financials.json: '"Revenues": {"value": 36148000000, "start": "2010-07-01", "end": "2010-12-31", "period_type": "half_year", "fy": 2011}'
  - Evidence: financials.json carries a stray 2010 half-year 'Revenues' fact (FY2011, \$36.148B) alongside the correct FY2026 facts. It looks like an SEC concept-tag artifact from the XBRL fetch. It is not referenced by any claim's source_claim_ids or grounding, so it does not affect any numeric check, but it is stale/irrelevant data in an evidence file.
  - Recommendation: Filter the SEC fact fetch to the reporting FY (or drop facts whose fy != event fy) so unrelated historical periods do not land in financials.json.

## Claim findings
- **[info]** claims.json#claim-021: 'GitHub now has 225 million users, with over 90% of the Fortune 500 choosing GitHub for AI-powered development.'
  - Evidence: Sampled claims where claim_text extends past the quoted substring were checked against full segment context and are fair. claim-021's 'Fortune 500' detail, claim-022's 'Copilot revenue accelerated over 60% quarter-over-quarter', and claim-025's 'added another gigawatt of capacity' are all stated in the same seg-0003 passage. claim-007/claim-044 margin-attribution ('Azure mix shift and AI infrastructure investment') matches Hood's seg-0004 wording. No cherry-picking or dropped qualifiers found in the sample.
  - Recommendation: None.
- **[info]** claims.json#claim-039: 'period: 3 months to 31 Dec 2025 / 3 months to 31 May 2026'
  - Evidence: Period labels are unambiguous and internally consistent: quarterly reported items use '3 months to 30 Jun 2026', full-year items '12 months to 30 Jun 2026', point-in-time balances (RPO claim-013, headcount claim-019, seats/users) 'as of 30 Jun 2026', and Q1 FY27 guidance '3 months to 30 Sep 2026'. Peer periods (claim-039/041 Dec-2025 quarter, claim-040 May-2026 quarter) match their evidence files. claim-001's '12 months to 30 Jun 2026' agrees with financials.json RevenueFromContractWithCustomerExcludingAssessedTax (full_year, 2025-07-01..2026-06-30). No quarter-vs-YTD confusion detected.
  - Recommendation: None.

## Outlook findings
- **[info]** outlook-brief.md: 'The near-term direction (into Q1 FY27, the 3 months to 30 Sep 2026) is continued double-digit company growth led by Intelligent Cloud, with Azure guided to ~45% constant-currency growth [claim-028]'
  - Evidence: Every material statement in the brief maps to a real claim id (all citations resolve; claim-042 is absent from claims.json and is never cited). Signs, units, and periods are used correctly: growth vs decline (MPC -4%/-5% cc), constant-currency vs USD, and cumulative vs incremental (88 datacenters 'this year' vs 31 'this quarter') all read correctly against the transcript. Base/upside/downside cases stay within what the cited claims establish and uncertainty is communicated honestly in section 9.
  - Recommendation: None.
- **[info]** outlook-brief.md: 'A fourth discovered peer, Apple, was deliberately excluded: its quarter reported on 30 Jul 2026, one day after the call, so its results were not knowable at the call and are not cited here.'
  - Evidence: Temporal integrity confirmed by reading source content, not metadata: the three cited peers (AWS/Google Dec-2025 quarter, Oracle May-2026 quarter) were all released before the 29 Jul 2026 call, and Apple's June-quarter release (web-005) self-dates its call to 30 Jul 2026 and is correctly excluded. No post-event information is used to characterize the pre-results setup.
  - Recommendation: None.
- **[low]** outlook-brief.md: 'Q4 revenue of \\$90B [claim-004] and EPS of \\$4.74 [claim-005] exceeded the \\$87.67B / \\$4.24 consensus [claim-038], a positive surprise [claim-043].'
  - Evidence: The bottom-line beat rests on EPS of \$4.74, which the transcript states is 'adjusted for the impact from our investment in OpenAI' AND also carries a net 27-cent benefit from discrete items (a \$3.2B Anthropic gain and lower-than-expected VRP expense, partly offset by XBOX severance/impairment). The brief flags the OpenAI adjustment in section 9 but does not mention the 27-cent discrete benefit. The beat conclusion still holds after removing those items (management explicitly said 'when adjusting for these items, we exceeded expectations across revenue, operating income and earnings per share'), so this is a completeness nuance, not an error.
  - Recommendation: Add one clause to section 2 or section 9 noting the ~\$0.27 discrete-item benefit in Q4 EPS, so the bottom-line beat is presented on a clean underlying basis.

## Process findings
- **[info]** validation.json: '"ok": true, "checked_claims": 44, "issues": [], "warnings": []'
  - Evidence: Confirmed present (not re-derived): validation.json.ok == true over 44 claims with zero issues, and outlook-validation.json.ok == true with no errors. Deterministic quote/numeric/citation checks therefore ran and passed upstream.
  - Recommendation: None.
- **[info]** manifest.json: 'sources[] with sha256 and byte_length for transcript.html, 55 raw web hits, and 10 evidence/web/*.md files'
  - Evidence: manifest.json exists with every source hashed; claims.json has 44 claims all with non-empty ids (claim-001..claim-045, claim-042 skipped in numbering and never cited); signal-card.md and outlook-brief.md both present. All mandatory stage artifacts are in place.
  - Recommendation: None.
- **[info]** signal-card.md: 'Reported Financial Performance / Costs Margins Efficiency / Demand Activity / Capacity Supply Execution / Current Guidance / Risk'
  - Evidence: Cross-sector appropriateness check: signal-card.md and outlook-brief.md use only industry-appropriate constructs for a cloud/software company (Azure, Microsoft Cloud, RPO, Copilot seats, datacenters, capex). 'Subscription' appears only where the transcript itself does (M365 consumer subscriptions); no churn/ARR/same-store/other foreign-industry template language leaked in. metrics.json entries are all cloud/software metrics with correct cumulative-vs-flow period tags.
  - Recommendation: None.

## Unverified items
- The unadjusted GAAP Q4 diluted EPS is not isolated in the transcript (only the OpenAI-adjusted $4.74 is given), and web-006 does not state whether its $4.24 consensus is GAAP or adjusted, so the exact magnitude of the EPS beat cannot be pinned down. The brief already discloses this limitation in section 9.
- The full-year-vs-quarter split for ratio metrics (gross margin 67% claim-007, operating margin 45% claim-008, Microsoft Cloud gross margin 65% claim-044) was judged from transcript ordering (these sit in Hood's quarterly-results passage) rather than cross-checked against 10-K line items; financials.json only carries revenue, net income, and diluted EPS, so these margin percentages could not be independently reconciled to SEC facts.