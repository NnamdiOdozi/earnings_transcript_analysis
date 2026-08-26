# Signal card template

`cli._render_signal_card` produces Markdown with this structure. This file documents
it for reference — you do not need to hand-author the card; it is generated only
after all claims pass validation.

```markdown
# Signal Card: <TICKER> — <EVENT_ID>

## Reported Financial Performance
- **reported** (Jane Smith): Revenue was $110 million, up 10% YoY.
  > "Revenue for the quarter was $110 million, up from $100 million a year ago." — seg-0002

## Current Guidance
- **forward_looking** (Bob Lee): Full-year revenue guidance is approximately $460 million.
  > "we are guiding full-year revenue to approximately $460 million" — seg-0003

## Risk
- **forward_looking** (Bob Lee): Management flagged currency and input-cost headwinds as key risks.
  > "We are watching foreign exchange headwinds and potential softness in input costs" — seg-0006
```

Sections appear in the order claim categories are first encountered in `claims.json`.
Each bullet shows the claim's status, speaker (if known), the plain-English claim
text, and the exact quote with its segment id as a blockquote directly beneath it —
so every line in the card is traceable back to source.
