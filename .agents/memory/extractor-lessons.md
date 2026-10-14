# Extractor lessons

Process guidance only, proposed by the outlook-reviewer and persisted by `earnings check-review`. Never facts, quotes, or numbers -- see produce-earnings-signal-card/SKILL.md.

- Every quoted phrase in the outlook brief must appear in the quote of the claim cited beside it; never attach a transcript quotation to a claim id that does not contain it.
- Before describing a segment's decline as demand weakness or criticising how management framed it, check the prepared remarks and the results release for management's own primary stated cause and extract it as a claim.
- When extracting pre-event expectations, capture the metrics the company missed as well as the ones it beat, so the brief cannot present a selective beat as a clean surprise.
- Record each claim value in the same sign and unit scale the source states it (a bracketed or 'expected' decline stays negative; a figure given in billions is not silently rewritten in millions), because numeric grounding matches the source's literal digits.
- Before writing in the brief that a source could not be used, re-open every archived evidence file for that entity, since a second capture of the same report is often cleanly extracted even when another is an unreadable chart deck.
- Keep each claim's quote self-sufficient: if claim_text asserts a figure or qualifier, that figure or qualifier must appear in the claim's own quote, not merely elsewhere in the same segment or page.
- When peer or competitor evidence is extracted, use it in the section whose judgment it actually bears on, rather than mentioning it only in the uncertainties section.
- When the brief attributes a statement to management, the cited claim must itself contain that statement; extract a new claim for it rather than citing a topically adjacent claim from the same part of the call.
- Every claim id cited in the brief body must also have its own entry in the evidence appendix, so no conclusion is left without a quote trail.
- For every derived claim, verify that each calculation operand has the same metric, scope, unit, basis, and intended period role before accepting mathematically valid arithmetic.
- Give a period only to claims whose quote actually fixes one; a comparison against historical standards or a general characterisation should carry no period rather than inherit the reporting quarter's.
- Before asserting that every entity in a comparison set shares a characteristic, confirm the stated metric for each entity individually rather than inferring it from a related metric on the same entity.
- When the brief states how many people raised a point, count distinct speakers across the cited claims rather than counting the citations themselves.
- When narrowing claim_text to what its quote supports, keep any scope-setting referent (business line, entity, customer segment) or speaker hedge that changes the meaning, by widening the quote to include it rather than deleting it from claim_text.
- Within a long management answer, extract every forward-looking statement that qualifies or reverses an earlier trajectory (for example a metric expected to rise near term but plateau or fall later in the plan), not only the near-term one.
- When a brief cites an earlier-period forecast revision, check whether the current call updated that forecast and extract the latest direction before using the earlier revision to frame a scenario.
