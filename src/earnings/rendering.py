from __future__ import annotations

import re

from .models import Claim, ReviewReport
from .runio import _now_iso

_BARE_DOLLAR_RE = re.compile(r"(?<!\\)\$")


def _escape_currency(text: str) -> str:
    """Escape bare '$' so Markdown renderers with LaTeX math support (KaTeX/MathJax --
    common in IDE previews) don't pair up two unrelated dollar amounts as one inline
    math span, mangling everything between them. Render-time only: never applied to
    claim.quote's underlying value used for exact-quote validation, only to the copy
    written into the .md file.

    Idempotent by construction (only matches a '$' NOT already preceded by '\\') --
    matters because outlook-brief.md's authoring template now tells the agent to
    write '\\$' directly; if agent-authored text carrying an existing '\\$' were ever
    escaped again with a naive .replace("$", "\\$"), it would become '\\\\$', which
    renders as a literal backslash followed by an unescaped '$' -- reopening the exact
    math-mode hazard this function exists to close.
    """
    return _BARE_DOLLAR_RE.sub(r"\\$", text)


def _render_review_report(ticker: str, event_id: str, report: ReviewReport) -> str:
    # report.reviewed_at is agent-self-reported (the subagent has no real clock) --
    # shown alongside, never in place of, checked_at (Python's actual clock at the
    # moment `check-review` validated this report), so a fabricated/rounded
    # agent timestamp is visibly distinguishable rather than silently trusted.
    lines = [
        f"# Review Report: {ticker.upper()} — {event_id}",
        "",
        f"**Verdict:** {report.verdict}",
        f"**Review mode:** {report.review_mode}",
        f"**Reviewed at (agent-reported):** {report.reviewed_at} (model: {report.model})",
        f"**Checked at (system clock):** {_now_iso()}",
        f"**Claims SHA-256:** `{report.claims_sha256}`",
        f"**Outlook brief SHA-256:** `{report.outlook_brief_sha256}`",
        f"**Review diff SHA-256:** `{report.review_diff_sha256 or 'n/a'}`",
        "",
        "## Summary",
        _escape_currency(report.summary),
        "",
    ]
    sections = [
        ("Source checks", report.source_checks),
        ("Claim findings", report.claim_findings),
        ("Outlook findings", report.outlook_findings),
        ("Process findings", report.process_findings),
    ]
    for title, findings in sections:
        lines.append(f"## {title}")
        if not findings:
            lines.append("_None._")
        for f in findings:
            lines.append(f"- **[{f.severity}]** {f.artifact}: {_escape_currency(f.passage)!r}")
            lines.append(f"  - Evidence: {_escape_currency(f.evidence)}")
            lines.append(f"  - Recommendation: {_escape_currency(f.recommendation)}")
        lines.append("")
    lines.append("## Unverified items")
    if report.unverified_items:
        for item in report.unverified_items:
            lines.append(f"- {item}")
    else:
        lines.append("_None._")
    return "\n".join(lines)


def _render_signal_card(ticker: str, event_id: str, claims: list[Claim], segments_by_id: dict) -> str:
    lines = [f"# Signal Card: {ticker.upper()} — {event_id}", "", f"_Generated: {_now_iso()}_", ""]
    by_category: dict[str, list[Claim]] = {}
    for claim in claims:
        by_category.setdefault(claim.category, []).append(claim)
    for category, group in by_category.items():
        lines.append(f"## {category.replace('_', ' ').title()}")
        for claim in group:
            speaker = f" ({claim.speaker})" if claim.speaker else ""
            # classification (e.g. "analytical_inference") must render alongside status --
            # without it, a reader cannot tell the pipeline's own inference apart from a
            # direct quote/fact, both of which render identically otherwise (found live,
            # 2026-08-28: a reviewer flagged an inference claim rendering indistinguishably
            # from a real quote, attributed to the speaker whose words it was derived from).
            lines.append(
                f"- **{claim.status}** [{claim.classification}]{speaker}: {_escape_currency(claim.claim_text)}"
            )
            location = claim.segment_id or claim.web_evidence_id
            lines.append(f'  > "{_escape_currency(claim.quote)}" — {location}')
        lines.append("")
    return "\n".join(lines)
