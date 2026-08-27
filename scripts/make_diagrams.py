"""Generate a staggered (serpentine) flow diagram as a standalone SVG.

Boxes flow left->right across a row, then drop down and flow right->left on the next
row (snake), matching the source figure. Parametric so both README diagrams share one
code path. Palette mirrors the original: grey input, blue skill, orange evidence,
green output, red stop.
"""
from __future__ import annotations

COLORS = {
    "inp": ("#ececec", "#bbbbbb"),
    "skill": ("#cfe3f7", "#8fb8dd"),
    "evid": ("#f7ddc8", "#e0b48f"),
    "out": ("#d6ecd2", "#a9d29c"),
    "stop": ("#f3c9c9", "#dd9999"),
    "gate": ("#f7edc8", "#d9b96a"),  # gold -- a GATE: the run stops here unless the check passes
}

BOX_W, BOX_H = 210, 96
GAP_X, GAP_Y = 70, 70
PAD = 24
COLS = 4


def _wrap_lines(text: str) -> list[str]:
    return text.split("|")


def render(boxes: list[dict], cols: int = COLS, extra=None) -> str:
    """boxes: list of {num, title, sub, kind}. sub may contain '|' for line breaks.
    extra: optional dict describing an off-flow stop box {after_index, box, label}.
    Snake layout: even rows L->R, odd rows R->L.
    """
    rows = (len(boxes) + cols - 1) // cols
    # extra stop box sits one row below its parent -> reserve a row if present
    total_rows = rows + (1 if extra else 0)
    width = PAD * 2 + cols * BOX_W + (cols - 1) * GAP_X
    height = PAD * 2 + total_rows * BOX_H + (total_rows - 1) * GAP_Y

    def col_x(col):
        return PAD + col * (BOX_W + GAP_X)

    def row_y(row):
        return PAD + row * (BOX_H + GAP_Y)

    # compute each box's (row, col) under snake ordering
    pos = []
    for i in range(len(boxes)):
        r = i // cols
        c = i % cols
        if r % 2 == 1:  # reverse direction on odd rows
            c = cols - 1 - c
        pos.append((r, c))

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="Segoe UI, Helvetica, Arial, sans-serif">',
        f'<rect width="{width}" height="{height}" fill="white"/>',
        '<defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="3" '
        'orient="auto" markerUnits="strokeWidth">'
        '<path d="M0,0 L8,3 L0,6 Z" fill="#666"/></marker></defs>',
    ]

    def box_rect(x, y, box):
        fill, stroke = COLORS[box["kind"]]
        parts = [
            f'<rect x="{x}" y="{y}" width="{BOX_W}" height="{BOX_H}" rx="10" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>'
        ]
        if box.get("num"):
            parts.append(
                f'<text x="{x+12}" y="{y+22}" font-size="13" fill="#999">{box["num"]}</text>'
            )
        cx = x + BOX_W / 2
        parts.append(
            f'<text x="{cx}" y="{y+40}" font-size="17" font-weight="600" '
            f'fill="#111" text-anchor="middle">{box["title"]}</text>'
        )
        subs = _wrap_lines(box.get("sub", ""))
        for j, line in enumerate(subs):
            parts.append(
                f'<text x="{cx}" y="{y+62+j*17}" font-size="13.5" fill="#555" '
                f'text-anchor="middle">{line}</text>'
            )
        return "".join(parts)

    def arrow(x1, y1, x2, y2):
        return (
            f'<path d="M{x1},{y1} L{x2},{y2}" stroke="#666" stroke-width="1.6" '
            f'fill="none" marker-end="url(#arrow)"/>'
        )

    # arrows between consecutive boxes (draw before boxes so heads tuck under)
    for i in range(len(boxes) - 1):
        r1, c1 = pos[i]
        r2, c2 = pos[i + 1]
        x1, y1 = col_x(c1), row_y(r1)
        x2, y2 = col_x(c2), row_y(r2)
        if r1 == r2:  # horizontal
            if c2 > c1:  # rightward
                svg.append(arrow(x1 + BOX_W, y1 + BOX_H / 2, x2 - 6, y2 + BOX_H / 2))
            else:  # leftward
                svg.append(arrow(x1, y1 + BOX_H / 2, x2 + BOX_W + 6, y2 + BOX_H / 2))
        else:  # vertical drop at the turn
            svg.append(arrow(x1 + BOX_W / 2, y1 + BOX_H, x2 + BOX_W / 2, y2 - 6))

    if extra:
        pr, pc = pos[extra["after_index"]]
        px, py = col_x(pc), row_y(pr)
        ex, ey = col_x(pc), row_y(pr + 1)
        svg.append(arrow(px + BOX_W / 2, py + BOX_H, ex + BOX_W / 2, ey - 6))
        mx = (px + BOX_W / 2 + ex + BOX_W / 2) / 2
        my = (py + BOX_H + ey) / 2
        svg.append(
            f'<rect x="{mx-30}" y="{my-11}" width="60" height="20" rx="4" fill="#f0f0f0"/>'
            f'<text x="{mx}" y="{my+3}" font-size="12" fill="#333" text-anchor="middle">'
            f'{extra["label"]}</text>'
        )
        svg.append(box_rect(ex, ey, extra["box"]))

    for i, box in enumerate(boxes):
        r, c = pos[i]
        svg.append(box_rect(col_x(c), row_y(r), box))

    svg.append("</svg>")
    return "\n".join(svg)


DIAG1 = [
    {"num": 1, "title": "You", "sub": "ticker + event id|+ transcript location", "kind": "inp"},
    {"num": 2, "title": "Codex/Claude Code", "sub": "agent · holds|full context", "kind": "inp"},
    {"num": 3, "title": "Skill 1", "sub": "build source|pack", "kind": "skill"},
    {"num": 4, "title": "Discover peers", "sub": "search &#8594; agent|picks ~4", "kind": "evid"},
    {"num": 5, "title": "Python", "sub": "ingest · sanitise|SEC · consensus/peers", "kind": "evid"},
    {"num": 6, "title": "Source pack", "sub": "hashed +|timestamped", "kind": "evid"},
    {"num": 7, "title": "Agent writes claims", "sub": "each claim +|exact quote", "kind": "evid"},
    {"num": 8, "title": "Skill 2", "sub": "produce signal card|+ validators", "kind": "skill"},
    {"num": 9, "title": "Signal card", "sub": "only if|validation passes", "kind": "out"},
]

DIAG2 = [
    {"num": 1, "title": "Choose event", "sub": "ticker +|call date", "kind": "inp"},
    {"num": 2, "title": "Load sources", "sub": "transcript ·|SEC · web", "kind": "inp"},
    {"num": 3, "title": "Clean and split", "sub": "remarks · Q&amp;A|· speakers", "kind": "evid"},
    {"num": 4, "title": "Lock evidence", "sub": "sha256 +|timestamp", "kind": "evid"},
    {"num": 5, "title": "Extract claims", "sub": "agent · each|w/ exact quote", "kind": "skill"},
    {"num": 6, "title": "Verify", "sub": "quote · number|calc-input · schema", "kind": "out"},
    {"num": 7, "title": "Calculate + draft", "sub": "Python deltas|&#8594; signal card", "kind": "out"},
    {"num": 8, "title": "Archive run", "sub": "runs/&lt;ticker&gt;/|&lt;event&gt;/", "kind": "out"},
]

DIAG2_EXTRA = {
    "after_index": 5,  # box 6 "Verify"
    "label": "any fail",
    "box": {"title": "No card", "sub": "exit 1", "kind": "stop"},
}

# Audit-focused view for docs/AUDITABILITY.md: same pipeline, annotated with the CHECK
# performed at each step. Gold boxes (kind "gate") are gates -- the run stops unless the
# check passes. sub carries the check in <=2 short lines (split on '|').
DIAG_AUDIT = [
    {"num": 1, "title": "Ingest source", "sub": "archive raw|+ SHA-256 hash", "kind": "inp"},
    {"num": 2, "title": "Sanitise", "sub": "strip invisible chars|· injection flag", "kind": "evid"},
    {"num": 3, "title": "Segment", "sub": "speaker-labelled|transcript", "kind": "evid"},
    {"num": 4, "title": "Agent writes claims", "sub": "each: exact quote|+ grounded number", "kind": "skill"},
    {"num": 5, "title": "Validate", "sub": "GATE &#8212; quote ·|number · calc recompute", "kind": "gate"},
    {"num": 6, "title": "Signal card", "sub": "only if all|checks pass", "kind": "out"},
    {"num": 7, "title": "Outlook brief", "sub": "GATE &#8212; cites|real claim ids", "kind": "gate"},
    {"num": 8, "title": "Reviewer", "sub": "GATE &#8212; fairness|· check-review", "kind": "gate"},
]

DIAG_AUDIT_EXTRA = {
    "after_index": 4,  # box 5 "Validate"
    "label": "any fail",
    "box": {"title": "No card", "sub": "run halts", "kind": "stop"},
}

if __name__ == "__main__":
    import pathlib

    # Emit into docs/ at the repo root (this script lives in scripts/).
    out = pathlib.Path(__file__).resolve().parents[1] / "docs"
    out.mkdir(exist_ok=True)
    (out / "flow_overall.svg").write_text(render(DIAG1))
    (out / "flow_pipeline.svg").write_text(render(DIAG2, extra=DIAG2_EXTRA))
    (out / "flow_audit.svg").write_text(render(DIAG_AUDIT, extra=DIAG_AUDIT_EXTRA))
    print(f"wrote {out}/flow_overall.svg, {out}/flow_pipeline.svg, {out}/flow_audit.svg")
