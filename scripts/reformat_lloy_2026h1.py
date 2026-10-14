"""Reformat the LLOY 2026 H1 results transcript (converted PDF text) into the header lines
`process._detect_speaker` accepts, before `earnings prepare`. Used for runs/LLOY/2026-h1.

Rewrites only header/banner lines; speech is untouched (diff the output to confirm):
  - "Question N:  Name, Firm."      -> "Name, Firm:"   (12 analysts, explicit allowlist below)
  - "Charlie Nunn" alone on a line  -> "Charlie Nunn:"
  - drops "N of 37" page banners and "SLIDE N - TITLE: ..." slide headings (colons mimic speakers)
Online questions read by the moderator ("Douglas Radcliffe: Question 9") are left as the moderator's.

Usage:
  python3 scripts/reformat_lloy_2026h1.py runs/LLOY/2026-h1/raw/transcript.converted.md OUT.md
  uv run earnings prepare --ticker LLOY --event-id 2026-h1 --transcript OUT.md ...
(copy the input out of the run folder first: a rerun of prepare archives raw/)
A template for other layouts: keep the allowlist approach, never a generic name heuristic."""
import re, sys

src, dst = sys.argv[1], sys.argv[2]
# Analyst headers exactly as they appear: "Question N:  Name, Firm."
ANALYSTS = {
    "Guy Stebbings": "BNP Paribas", "Ben Toms": "RBC", "Ben Caven-Roberts": "Goldman Sachs",
    "Andrew Coombs": "Citi", "Amit Goel": "Mediobanca", "James Invine": "Rothschild & Co Redburn",
    "Christopher Cant": "Autonomous", "Perlie Mong": "Bank of America", "Nicolas Payen": "Keppler Cheuvreux",
    "Alvaro Serrano": "Morgan Stanley", "Ed Firth": "KBW", "Sheel Shah": "JP Morgan",
}
COLONLESS = {"Charlie Nunn"}  # management headers printed without a colon
q_re = re.compile(r"^Question \d+:\s+(?P<name>[^,]+?)\s*,\s*(?P<firm>[^.]+?)\.?\s*$")
page_re = re.compile(r"^\s*\d+ of 37\s*$")  # PDF page banners, e.g. "17 of 37"
slide_re = re.compile(r"^\s*SLIDE \d+\b")  # slide-title headings, not speech; their colons mimic speaker headers
out, n_q, n_m, n_p = [], 0, 0, 0
for line in open(src, encoding="utf-8").read().split("\n"):
    if page_re.match(line) or slide_re.match(line):
        n_p += 1; continue
    m = q_re.match(line)
    if m and m.group("name") in ANALYSTS:
        assert ANALYSTS[m.group("name")] == m.group("firm").strip(), line
        out.append(f"{m.group('name')}, {ANALYSTS[m.group('name')]}:"); n_q += 1
    elif line.strip() in COLONLESS:
        out.append(f"{line.strip()}:"); n_m += 1
    else:
        out.append(line)
assert n_q == len(ANALYSTS), f"rewrote {n_q} analyst headers, expected {len(ANALYSTS)}"
open(dst, "w", encoding="utf-8").write("\n".join(out))
print(f"analyst headers rewritten: {n_q}; colon-less management headers fixed: {n_m}; page banners + slide titles removed: {n_p}")
