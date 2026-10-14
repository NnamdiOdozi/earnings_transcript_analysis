# Review Report: LLOY — 2026-h1

**Verdict:** pass_with_warnings
**Review mode:** full
**Reviewed at (agent-reported):** 2026-10-14T07:20:00Z (model: claude-opus-5-5; reasoning effort: not_applicable)
**Checked at (system clock):** 2026-10-14T06:56:14Z
**Claims SHA-256:** `b859620f1b8eab65502abca190e1326d66ca91e826b5addc695692a483e4ca5b`
**Outlook brief SHA-256:** `d7793358806d4bbcf0579be2b7b2c50f25dfe52e7dec7fbb5f2268da26b9b501`
**Review diff SHA-256:** `n/a`

## Summary
The run passes with warnings: no high or critical findings, four medium. The claims are well grounded overall; reading all 177 against full context found one scope error (claim-130 now reads as 70% of all revenue when the figure applied to strategic-initiative revenue on a broad digital-and-AI definition), three low-severity wording issues, and a coverage gap: the NIM-plateau outlook, the Q2 macro-forecast improvement, the TNAV growth expectation and the operating-lease depreciation recovery were not extracted. In the brief, the downside case frames the economy using a superseded Q1 macro cut although management said forecasts improved modestly at H1, and the peer paragraph concludes that Lloyds depends more than its peers on efficiency gains with no peer-plan evidence. Lower-severity points: HSBC's post-event timing is undisclosed, one analyst's view is generalised to 'analysts', and the upside observable is weakly diagnostic. Deterministic gates, injection scan and Jev dispositions are all in order.

## Claim review coverage
- Claims accounted for: 177
- Reviewed, no finding: 173
- Finding raised: 4
- Could not verify: 0
- Carried forward unchanged from the previous round: 0

## Source checks
- **[info]** raw/transcript.txt: 'LLOYDS BANKING GROUP PLC – 2026 HALF YEAR RESULTS & STRATEGY UPDATE PRESENTATION TRANSCRIPT ... Thursday 30 July, 2026 – 9.30am'
  - Evidence: Read the transcript in full (prepared remarks and the whole Q&A). It is the Lloyds H1 2026 results and Accelerate 2030 strategy presentation, dated 30 July 2026, which matches manifest.json event_date 2026-07-30. Speakers and analyst attributions in claims match the transcript's speaker headers.
  - Recommendation: None.
- **[info]** evidence/web/web-001.md: 'Lloyds Banking Group plc (LSE: LLOY) reported a 33% rise in first-quarter statutory profit before tax to £2.03 billion'
  - Evidence: Genuine 29 April 2026 article on Lloyds' Q1 2026 results; it supports the Q1 consensus beat, the NII guidance lift from 'around' to 'greater than' £14.9 billion, the Q1 cut to Lloyds' own macro base case (GDP 0.5% from 1.2%, unemployment 5.6% by Q4) and the unchanged £1.95 billion motor finance provision. It also states Q1 reiterated RoTE above 16% and capital generation above 200 basis points, which supports the 'reiterated rather than raised' reading. Pre-event.
  - Recommendation: None.
- **[info]** evidence/web/web-006.md: 'Closing price 10/12/2026 03:59 PM Eastern'
  - Evidence: MarketBeat page for the NYSE ADR (LYG). The page itself was refreshed in October 2026, after the event, and lists an estimated Q3 date, so it is a living page. The figures actually extracted (Q1 ADR EPS and revenue against consensus) are labelled as released 29 April 2026, so nothing post-event is used.
  - Recommendation: None.
- **[info]** evidence/web/web-011.md: '| Currency in GBP | Current qtr. (Jun 2026) | Next qtr. (Sept 2026) | Current year (2026) | Next year (2027) |'
  - Evidence: Undated Yahoo Finance consensus snapshot. Its 'current quarter' is June 2026 and its earnings history stops at 31 Mar 2026, which places the snapshot between the Q1 and H1 results, as the claim's caveat says. Consistent with pre-results consensus; exact capture date cannot be confirmed.
  - Recommendation: None.
- **[info]** evidence/web/web-002.md: 'Common Equity Tier 1 (CET1) ratio (6) 13.2% 14.3% (110bps) 14.0% (80bps)'
  - Evidence: NatWest H1 2026 interim results; the RoTE 19.7%, income ex notable items, 46.0% cost:income and RoTE greater than 19% guidance quotes are all present. The results URL carries 31 July 2026, the day after Lloyds' event. NatWest's 13.2% CET1 is net of foreseeable items (its pro forma ratio excluding them is 14.2%), so it is broadly comparable with Lloyds' 13.1% after distributions.
  - Recommendation: None.
- **[low]** evidence/web/web-009.md: 'Georges Elhedery Group CEO 4 August 2026'
  - Evidence: HSBC interim release (web-009, and the HK announcement web-014) is dated 4 August 2026, five days after Lloyds' event. The quotes used (profit before tax \$19.5bn, revenue \$37.7bn, CET1 14.1%, cost efficiency 46.2% in the 1H26 column) are present. The claims carry a post-event caveat, but this is post-event evidence used in the brief's peer comparison (see outlook findings).
  - Recommendation: Acceptable as a post-results peer comparison, provided the brief discloses HSBC's timing as it does NatWest's.
- **[info]** evidence/web/web-013.md: 'Barclays delivered a return on tangible equity (RoTE) of 14.8% in H126, announced £2.3bn total capital distributions'
  - Evidence: Barclays H1 2026 results announcement, approved by its board on 27 July 2026, before the event. RoTE, CET1 14.3%, buyback of up to £1.0bn and the raised c.£31.5bn income target are all present. Santander sources (web-005, web-010, web-015) are dated 22 July 2026 and contain the revenue, CET1, efficiency, TSB and underlying RoTE quotes used.
  - Recommendation: None.

## Claim findings
- **[medium]** claims.json#claim-130: 'Nunn said Lloyds had previously given figures linking 70% of revenue and 60% of gross cost saves to digital and AI.'
  - Evidence: Full context (seg-0047): 'Back in November when Ron and I did our digital and AI seminar, looking to the gross cost saves and the strategic initiative revenues, I know we did give you 70% of the revenue was linked to digital and AI ... And that was a broader definition just to be clear of digital and AI.' The 70% applies to strategic-initiative revenues (about £2 billion), not to group revenue, and it is on a broader definition than the narrow generative/agentic AI measure. The claim_text reads as 70% of all revenue. The Jev disposition records that 'strategic' and 'on a broader definition' were removed to make claim_text traceable to the quote, which is how the scope was lost.
  - Recommendation: Widen the quote to include 'looking to the gross cost saves and the strategic initiative revenues' and 'that was a broader definition', then restore 'strategic-initiative revenue' and the broader-definition qualifier in claim_text.
- **[low]** claims.json#claim-174: 'The 2028 RoTE target sat below analyst consensus, which management attributed to prudent assumptions and a larger equity base.'
  - Evidence: The only source for 'below consensus' is one analyst's question ('It was a bit light versus consensus, though I appreciate there's a greater than symbol'). Chalmers' reply calls it 'on the lower end of consensus maybe'. The claim states as fact that the target sat below consensus, which hardens an analyst's characterisation that management only partly accepted.
  - Recommendation: Rewrite as 'An analyst said the 2028 RoTE target looked light versus consensus; Chalmers said it may be at the lower end of consensus and pointed to prudent assumptions and a larger equity base.'
- **[low]** claims.json#claim-036: 'higher than Q1 on model updates and non-repeat of releases'
  - Evidence: The quote says 'This was slightly higher than Q1'. The claim_text drops 'slightly', making a modest rise in the quarterly pre-MES charge read as a plain increase.
  - Recommendation: Restore 'slightly higher than Q1'.
- **[low]** claims.json#claim-031: 'Insurance, pensions and investments grew 19% versus the first half of 2025.'
  - Evidence: In context the 19% sits in the other-income section of the prepared remarks (other income by division), so it is IP&I's income contribution, not a balance or AUA figure. The claim_text names no metric, so a reader of claims.json alone cannot tell what grew.
  - Recommendation: Name the metric, e.g. 'IP&I other income rose 19% versus H1 2025'.
- **[medium]** claims.json: 'Over time, over the course of this plan indeed, we do expect that NIM to broadly plateau, maybe even at the later end of the plan, come off a little bit.'
  - Evidence: Extraction is meant to be exhaustive, but several material forward-looking statements were not extracted although their segments are marked claims_extracted in coverage-receipt.json. (1) seg-0058: Chalmers said NIM will broadly plateau over the plan and may come off a little late in the plan, with growth becoming volume-led; only the near-term 'tick up every quarter' statement was captured. (2) seg-0004: 'we updated our economics in the second quarter. This resulted in a small Q2 release from modest improvements to our forecast' - the H1 direction of the macro forecast is missing. (3) seg-0004: 'we continue to expect material TNAV per share growth in both the short and the medium term' and the 1p buyback accrual that 'will mechanically reverse in Q3'. (4) seg-0004 and seg-0034: operating lease depreciation expected to 'revert back to a normalised run rate' and 'recover somewhat' in Q3 and Q4. The coverage receipt works at segment level, so it cannot show that these individual statements were skipped.
  - Recommendation: Add claims for each of the four statements above, in particular the NIM plateau and the Q2 macro forecast improvement, which bear directly on the brief's NII narrative and downside case.

## Outlook findings
- **[medium]** outlook-brief.md: 'A second route is the economy. The plan assumes unemployment peaks around 5.5% in early 2027, after Lloyds cut its GDP assumption at Q1 [claim-067][claim-149].'
  - Evidence: The sentence frames the macro outlook as deteriorating by leading with the Q1 cut. That cut has been superseded: at H1 Chalmers said the Q2 economics update produced 'a small Q2 release from modest improvements to our forecast', and claim-067's 5.5% unemployment peak is itself lower than the 5.6% Q1 forecast in claim-149. The brief therefore uses an out-of-date data point to imply a direction of travel that the current call contradicts. The downside scenario itself (a sharper rise in unemployment testing the asset quality range) is legitimate; the framing is not.
  - Recommendation: Once the Q2 macro update is extracted, rewrite the sentence to say the H1 forecast improved modestly from Q1, then keep the unemployment-shock downside as a scenario. Alternatively, drop the 'after Lloyds cut its GDP assumption at Q1' clause.
- **[medium]** outlook-brief.md: "Our reading is that Lloyds' plan depends more than its peers' on future efficiency gains to close the return gap."
  - Evidence: No claim in claims.json describes any peer's plan or its reliance on efficiency, so 'more than its peers'' has no evidential base. The 'return gap' exists only against NatWest: claim-170 shows Lloyds' RoTE above Barclays' and Santander's. The cost comparison underlying the inference is on different definitions, as claim-172's own caveat says (NatWest excludes litigation and conduct; HSBC and Santander use their own efficiency ratios). This is an unsupported inferential leap presented in confident prose.
  - Recommendation: Narrow the sentence to what the cited claims show, e.g. 'Lloyds' cost:income ratio is higher than the three peers that report a comparable measure, on differing definitions, and its 2030 target of below 45% implies the gap should narrow.' Otherwise extract peer-plan evidence before comparing plans.
- **[low]** outlook-brief.md: "Its cost:income ratio was higher than NatWest's, HSBC's and Santander's [claim-172][claim-034][claim-155][claim-164][claim-167]."
  - Evidence: HSBC's results (claim-164, from web-014) were published on 4 August 2026, after Lloyds' event, and claim-164 carries the caveat 'Reported after Lloyds' event.' The uncertainties section discloses only NatWest's timing ('NatWest reported the day after Lloyds' event'), so the HSBC caveat is not honoured in the prose.
  - Recommendation: Amend the 'Peer timing and bases' bullet to say NatWest (31 July) and HSBC (4 August) both reported after Lloyds' event.
- **[low]** outlook-brief.md: 'The first reaction from analysts was that the 2028 target looked light.'
  - Evidence: Only one analyst (Ben Toms, RBC, claim-090) raised this. A second analyst (claim-102) argued the opposite direction for capital generation, saying his own numbers gave 'a lot more than the 225 bps'. 'The first reaction from analysts' generalises one speaker into a consensus reaction.
  - Recommendation: Write 'One analyst said the 2028 RoTE target looked light versus consensus' and keep the existing citations.
- **[low]** outlook-brief.md: 'observable as a hedge yield running above the guided path of about 2.8% in Q2 rising to around 2.9% by year end [claim-110].'
  - Evidence: The upside mechanism is refinancing at market rates above the plan's 3.7% assumption. That plays out mainly from 2027 onward: Chalmers described the 2.8% to 2.9% path as the start of a glide that 'builds into the 3.7% refinancing rate', and web-001 records the hedge as roughly 90-95% locked in for 2026. A 2026 yield is therefore a weak signal of whether the upside is occurring. The causal chain is sound, but the observable chosen will not discriminate.
  - Recommendation: Use an observable that tracks the mechanism, e.g. management's reported hedge reinvestment rate against the 3.7% assumption, or hedge income against the greater-than-£8 billion 2027 guide in claim-027.
- **[low]** outlook-brief.md: "Chalmers' rule of thumb shows the leverage: each 1% of RoTE adds roughly 10-15 basis points of capital generation [claim-103]."
  - Evidence: The brief honours claim-103's caveat by calling it a rule of thumb, but uses it only as upside leverage. In context Chalmers used it to explain why guidance (greater than 225 basis points) sits below the roughly 260 the rule implies at a circa 20% RoTE: RWA build, a modest rise in RWA density and planning prudence (claim-104, claim-120). He also said consensus RWA growth is 'quite possibly' below the bank's plan (claim-122, claim-177). The brief omits this counterweight, which bears on distributions.
  - Recommendation: Add one sentence noting that management attributes the gap between the rule of thumb and its capital generation guidance to faster RWA growth and higher RWA density, citing claim-104 and claim-120.
- **[low]** outlook-brief.md: 'Lloyds launched its first interim share buyback, of £1 billion ... [claim-042][claim-016]; AI benefits are not quantified to 2030. Management linked earlier revenue and cost targets to digital and AI only on a broad definition [claim-130].'
  - Evidence: Both statements are accurate against the transcript ('today we announce our first interim share buyback'; Nunn declined to give a 2030 AI number, and said the 70%/60% figures used 'a broader definition'). However, neither 'first' nor 'not quantified to 2030' nor 'broad definition' appears in the cited claims, so the citation trail does not support the specific proposition.
  - Recommendation: Extract claims carrying 'first interim share buyback' and Nunn's decision not to quantify AI benefits to 2030, and cite them; the broad-definition point will be carried once claim-130 is fixed.
- **[low]** outlook-brief.md: "The only pre-results consensus in this run is full-year revenue, and its definition need not match Lloyds' own [claim-152]."
  - Evidence: claim-152 itself also carries a pre-results June-quarter revenue estimate (5.4B) and a 2027 estimate, so 'only full-year revenue' understates what the cited claim holds. The headline point (no first-half profit or RoTE consensus) is correct.
  - Recommendation: Write 'The only pre-results consensus in this run is revenue (quarterly and full-year), on a vendor definition that need not match Lloyds' own.'

## Process findings
- **[info]** claims/validation.json: '"ok": true, "checked_claims": 177'
  - Evidence: validation.json.ok == true with 177 claims checked, 0 issues and 0 warnings; confirmed present, not re-derived. manifest.json declares layout_version 2, and all claims have non-empty ids.
  - Recommendation: None.
- **[info]** outlook/outlook-validation.json: '"ok": true'
  - Evidence: outlook-validation.json.ok == true with no errors or warnings; it records claims_sha256 and outlook_brief_sha256, which this report copies. outlook-brief.md exists. Confirmed present, not re-derived.
  - Recommendation: None.
- **[info]** injection-scan.json: '"finding_count": 0'
  - Evidence: The prompt-injection scan ran 25 patterns and found nothing; there were no hits to judge. segmentation-report.json shows 64 segments, one omission (the Q&A heading) and no near-miss speakers.
  - Recommendation: None.
- **[info]** claims/jev-dispositions.json: '"defect": 35'
  - Evidence: Every defect in claims/jev-triage.json (35), claims/jev-coverage-triage.json (2) and outlook/jev-triage.json (19) has a recorded disposition. I re-read the rejected ones against the transcript. The rejections of the claim-075 'contradicts' flags are correct ('higher than this' refers to the mid-single-digit CAGR). The claim-125 rejection is defensible because Nunn ties slower deposit growth to competitive pressure in the same answer. The claim-014 'benign' rejection is supported by 'early warning indicators remain benign'. One 'fixed' disposition (claim-130::claim_text_traceable) introduced the scope error reported under claim findings.
  - Recommendation: When fixing a traceability flag, widen the quote rather than deleting a scope qualifier (already recorded as an extractor lesson).
- **[info]** claims/history: '"claim_text_quote_traceable": 16'
  - Evidence: Five claim attempts. Attempt 1 had 16 claim_text_quote_traceable issues, 3 claim_text_numeric and 1 values_present; attempt 2 had 2 claim_text_quote_traceable issues; attempts 3 to 5 were clean. The repeated failure type is already covered by existing extractor lessons on self-sufficient quotes and on widening the quote rather than deleting scope, so no new lesson is proposed from it.
  - Recommendation: None.
- **[info]** evidence/financials.json: '{}'
  - Evidence: financials.json is empty: Lloyds has no SEC structured facts in this run. The item-4 cross-check of claim periods against SEC period_type/start/end could not be performed. I checked periods against the transcript's own cues instead; the 6-month, 3-month and as-of labels match the 'H1', 'in the quarter'/'Q2' and 'ended the half' wording.
  - Recommendation: None.

## Unverified items
- Claim period labels could not be cross-checked against SEC-derived facts because evidence/financials.json is empty for this run; they were checked against transcript wording only.
- web-011 (Yahoo consensus) is undated; its pre-results timing is inferred from the page's own 'current quarter' and earnings-history columns, not from a capture date.
- The very large HSBC interim report (web-004) and the Barclays 6-K wrapper (web-003) were not read in full; they are marked deliberately_immaterial in the coverage receipt and no claim cites them.