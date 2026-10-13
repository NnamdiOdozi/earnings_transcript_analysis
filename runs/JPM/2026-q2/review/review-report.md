# Review Report: JPM — 2026-q2

**Verdict:** pass_with_warnings
**Review mode:** full
**Reviewed at (agent-reported):** 2026-10-13T23:30:00Z (model: claude-opus-5-5; reasoning effort: not_applicable)
**Checked at (system clock):** 2026-10-13T22:50:00Z
**Claims SHA-256:** `a618b84d2943b8b30d4de5970da025a61b5e1307e94ef2956bc8b75bb356bed4`
**Outlook brief SHA-256:** `65b2369b55928442d47cf72a5ce006e15a583358ebf2fd565df9168d3d22979f`
**Review diff SHA-256:** `n/a`

## Summary
The run is well grounded. Its sources are genuine, its temporal handling is careful (post-event pages are labelled, and a living pre_event-dated page showing actual results was correctly excluded), and every Jev flag was dispositioned. I found no high-severity issue. The main warning is in the brief's Business drivers section: it reads JPM's equal expense and revenue growth as JPM 'reinvesting more' than its peers. That ignores management's evidence that the expense growth was largely revenue-linked pay, that margins rose, and that dollar operating leverage was positive, and it drops claim-163's caveat that the expense and revenue growth rates may not share a basis. One claim (claim-035) lost its 'Wholesale' scope when it was trimmed to its quote, so it now reads as firm-wide deposit outperformance. Smaller issues: the brief overstates Equities' share of the revenue spike, says underwriting deterioration was 'across the market' when Dimon said it was not across the board, and cites regulation only as an upside. claim-116 drops a hedge, and a labour-market conditioning statement on consumer credit was never extracted.

## Claim review coverage
- Claims accounted for: 166
- Reviewed, no finding: 164
- Finding raised: 2
- Could not verify: 0
- Carried forward unchanged from the previous round: 0

## Source checks
- **[info]** normalized/transcript.jsonl: 'n/a'
  - Evidence: All 109 segments read in full. The transcript is a genuine JPMorganChase 2Q26 call dated 14 Jul 2026, matching manifest event_date 2026-07-14. Segmentation merges some speaker turns into one segment (seg-0014, seg-0026, seg-0040, seg-0062, seg-0074 each carry both the analyst and the answering executive), but every claim drawn from those segments names the speaker who actually said the quoted words.
  - Recommendation: None for this run; the merged turns are a segmentation limitation that the extractor handled correctly.
- **[info]** evidence/web/web-006.md: 'Jul 14, 2026 12:00 PM'
  - Evidence: A genuine TradingKey preview of JPM's Q2 2026 results. The timestamp is after JPM's 7 a.m. release, but the content is entirely pre-release (it discusses what to watch and states no actual results). The extractor recorded that timing caveat on every claim drawn from this page, and the brief repeats it.
  - Recommendation: None.
- **[info]** evidence/web/web-001.md: '| Actual 5.07 4.85 | Actual 4.63 4.85 | Actual 5.94 5.47 | Actual 7.70 5.59 |'
  - Evidence: A live WSJ estimates page captured on 13 Oct 2026, three months after the event. It is used only to report what the reported EPS turned out to be, and both the claim and the brief label it as post-event. The 7.70 figure is independently consistent with evidence/financials.json: the SEC half-year diluted EPS of 13.63 less Q1's 5.94 gives 7.69.
  - Recommendation: None.
- **[info]** evidence/web/web-011.md: 'EPS BEAT 5.59 6.14 +9.84%'
  - Evidence: web-evidence.jsonl marks this page temporal_status 'pre_event', yet its content already shows the actual results. It is a living page that was updated after the call, and its revenue 'actual' of 82.46B is plainly wrong. No claim cites it, and the brief's uncertainty section correctly says a second aggregator page showing actual results was excluded as an expectation source.
  - Recommendation: None for this run. It is a live example of why a pre_event date label cannot be trusted on its own.
- **[info]** evidence/web/web-012.md: 'n/a'
  - Evidence: The peer sources are genuine company releases or slide decks dated 14 Jul 2026: Bank of America (web-012 press release, web-007 slides), Citi (web-003 release, web-013 slides), Wells Fargo (web-004), and Goldman Sachs (web-005, web-010). Every peer quote in claim-135 to claim-158 was found in its file, and the surrounding context matches the claim, including entity, quarter and growth basis. For example, Bank of America's 11.2% CET1 is the Standardized ratio, the same basis as JPM's 14.1%.
  - Recommendation: None.

## Claim findings
- **[medium]** claims.json#claim-035: 'Barnum said first-half deposit growth outperformed expectations, reflecting franchise strength and share gains and partly the lending environment, particularly NBFI and data-centre lending.'
  - Evidence: Shifted scope. In seg-0013 Barnum opens with 'let me actually start with Wholesale. So, Wholesale deposit growth was quite strong this quarter actually and has been for the first half of the year', and only then says 'the first half of the year has outperformed our expectations'. The outperformance he describes is Wholesale deposits only. He then turns to Consumer separately, where growth is merely 'in line with our expectations' and yield-seeking outflows remain a risk. Because claim_text drops 'Wholesale', it reads as a firm-wide statement that deposit growth beat expectations, which the segment does not say. The Jev disposition marked this claim 'fixed' by removing content outside the quote, and that trimming is what removed the scope word. The brief itself correctly writes 'Wholesale deposit growth', so the brief is unaffected, but the signal card shows the claim without that scope.
  - Recommendation: Widen the quote to include 'Wholesale deposit growth was quite strong this quarter actually and has been for the first half of the year', and restore 'Wholesale' in claim_text.
- **[low]** claims.json#claim-116: 'Dimon said performance will not follow a bell curve and there will be outliers, as in the Great Financial Crisis.'
  - Evidence: Possibility turned into certainty, with a dropped condition. The full sentence in seg-0091 is 'when there's a credit cycle, and there will be a credit cycle, how will everybody perform. And I don't think it's going to be like a bell curve of performance. I think there'll be some outliers'. claim_text drops both the hedge ('I don't think', 'I think') and the condition that this refers to how lenders would perform when the credit cycle turns. As written, it reads as an unconditional prediction. The brief restores the condition ('when credit turns'), so the problem is confined to the claim and the signal card.
  - Recommendation: Rewrite as 'Dimon said he does not think performance will follow a bell curve when the credit cycle turns, expecting some outliers as in the Great Financial Crisis', and widen the quote to include the credit-cycle clause.
- **[low]** claims.json: "But as I always say, when it comes to Consumer credit performance, it's just about the labor market. And so, you're not going to hear anything from me that's new or differentiated about the labor market. Like we all see the same numbers, and it's been surprisingly resilient. So, for now, that's the narrative."
  - Evidence: Coverage gap in seg-0076. This is the CFO's own statement of the single driver of consumer credit performance, with a 'for now' qualifier, and no claim records it. That segment yielded claims on spend, delinquencies, the K-shaped narrative and the real-wage watch area, but not this conditioning statement. As a result the brief's 'Consumer credit is benign' paragraph could not state the condition management attached to that view.
  - Recommendation: Extract a management_opinion claim for this sentence. The brief's consumer credit paragraph can then say that the benign view is explicitly conditional on the labour market.

## Outlook findings
- **[medium]** outlook-brief.md: 'Expenses rose 15%, matching adjusted revenue growth [claim-003][claim-002][claim-163]. ... Our reading is that JPM is reinvesting more of its revenue growth than its peers, which are, for now, converting more of theirs into earnings.'
  - Evidence: There are three problems with this passage. First, it is an unsupported inferential leap. The brief's own cited evidence attributes the expense growth largely to volume- and revenue-related expense (claim-003). It also shows that \$1.5 billion of expense was booked against \$6.5 billion of capital-markets outperformance (claim-075), which is revenue-linked pay rather than reinvestment. Second, it ignores counterevidence. Dimon said margins 'actually went up this quarter, not down' (claim-055), yet the brief cites that claim only for 'a crazy notion'. Dimon also said operating leverage was 'definitely positive' in dollar terms (claim-069), and the brief omits this. Equal 15% growth on a revenue base far larger than the expense base means JPM did convert revenue growth into earnings. Third, a caveat is not honoured: claim-163 records that JPM's revenue growth is ex-significant items while the expense growth basis is not stated, but the brief writes 'matching' as though the two were measured on the same basis.
  - Recommendation: Replace the 'reinvesting more' reading. State that JPM's percentage operating leverage was roughly flat while peers' was positive, but that management attributes most of the expense growth to revenue-linked costs and says margins rose and dollar operating leverage was positive (cite claim-055 and claim-069). Carry claim-163's basis caveat in the sentence.
- **[low]** outlook-brief.md: 'The revenue spike, by contrast, rests largely on an Equities result management itself called hard to repeat [claim-018][claim-031].'
  - Evidence: claim-002 lists four drivers of the 15% adjusted revenue growth: Markets revenue, higher asset management fees, higher Investment Banking revenue, and higher deposit and loan balances. Equities is only one part of Markets. Nothing in the run gives a dollar split showing that Equities accounts for most of the increase, so 'rests largely on' goes further than the evidence. Section 7 makes the more accurate point, that 'part of this quarter's 15% adjusted revenue growth may simply not recur'.
  - Recommendation: Write 'rests in part on Markets, especially an Equities result management itself called hard to repeat', or cite evidence of Equities' share of the increase.
- **[low]** outlook-brief.md: 'He also described a mild deterioration in credit underwriting across the market, including more PIK and weaker covenants'
  - Evidence: The quote behind claim-115 says explicitly 'this is not across the board, by the way. It's more some players than others.' claim_text itself says the deterioration varies by player. 'Across the market' reverses that scope qualifier.
  - Recommendation: Write 'a mild deterioration in credit underwriting among some lenders, not across the board'.
- **[low]** outlook-brief.md: "Regulatory relief is a third possible lever: Dimon set out specific changes he wants to capital rules [claim-059], but nothing in this run's evidence shows they will happen."
  - Evidence: The brief treats regulation only as a possible upside. Management's own statement that the short-term wholesale funding change to the GSIB score 'disproportionately' increases the burden on banks like JPM (claim-061) is not cited anywhere in the brief. The preview's roughly \$20 billion G-SIB capital hit (claim-133) appears only in the uncertainties section, as a third-party figure. A brief that cites only the favourable side of a two-sided regulatory picture is a mild case of selective citation, especially next to the brief's 'Capital is ample' and buyback/deployment upside.
  - Recommendation: Add the GSIB/short-term wholesale funding headwind (claim-061) to the capital paragraph or the downside case, alongside the relief scenario.

## Process findings
- **[info]** claims/validation.json: 'n/a'
  - Evidence: Confirmed present, not re-derived. validation.json.ok == true, with 166 claims checked and 0 issues. outlook/outlook-validation.json.ok == true, with 0 errors and 0 warnings, and it records claims_sha256 and outlook_brief_sha256, which were copied into this report. manifest.json declares layout_version 2 and lists hashed sources. Every claim has a non-empty id, and outlook/outlook-brief.md exists. claims.json has no calculation blocks, so item 4 was a semantic check of each value's metric, unit, entity, scope and period against its source. That check found no misassigned figure and no period label that conflicts with evidence/financials.json, whose only facts are half-year figures that no claim labels as quarterly.
  - Recommendation: None.
- **[info]** injection-scan.json: 'n/a'
  - Evidence: Clean scan: 25 patterns, 0 findings. A read of all 109 segments and the cited web files also found no text addressed to an agent.
  - Recommendation: None.
- **[info]** claims/jev-dispositions.json: 'n/a'
  - Evidence: Every Jev defect has a recorded disposition. Claims triage: 135 defects and 83 checks. Coverage triage: 0 defects and 2 checks (seg-0049 and seg-0084), which I re-read and agree are immaterial. Outlook triage: 22 defects and 36 checks. I spot-read the 'rejected' dispositions against the claims and the brief, and their reasons survive. Two of the 'fixed' dispositions (claim-035 and claim-116) are the edits that introduced or left the defects raised in claim_findings above: trimming claim_text to the quote removed a scope word in one claim and a hedge and condition in the other. Every caveat on a cited claim was checked against the brief's prose. All are honoured (approximations written as 'about' or 'approximately', floors as 'more than', the adjusted basis flagged) except claim-163's expense-basis caveat, which is raised in outlook_findings.
  - Recommendation: When a Jev 'claim_text_traceable' flag is fixed by trimming claim_text, check that the trim did not drop a scope or hedge word. Where it would, widen the quote instead.
- **[info]** claims/history/attempt-0001_20261013T223240Z/receipt.json: 'n/a'
  - Evidence: There were three extraction attempts. Attempt 1 failed with a single claim_text_quote_traceable issue. Attempts 2 and 3 passed with no issues. No check type failed in two or more attempts, so the history yields no lesson.
  - Recommendation: None.
- **[info]** outlook-brief.md: 'n/a'
  - Evidence: Cross-sector appropriateness check: the signal card and brief use banking-appropriate metrics throughout (NII, CET1, RWA, ROTCE, net charge-offs, deposit betas, IB fees). No template language from another industry appears.
  - Recommendation: None.

## Unverified items
- JPM's own earnings release and financial supplement were not archived as web evidence. The search hits for them are in raw/web but were never extracted. As a result I could not check whether the $27.3 billion expense figure in claim-003 is reported or adjusted, nor the size of the significant items that separate the adjusted $6.14 EPS from the reported 7.70. The brief correctly flags both as open.