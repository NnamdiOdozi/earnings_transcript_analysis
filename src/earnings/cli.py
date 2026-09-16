"""argparse CLI: `earnings prepare` and `earnings analyze`.

`prepare` builds a source pack (raw archive, normalized transcript, manifest,
financials evidence, web-search official-source evidence) for one ticker/event.
`analyze` reads an existing claims.json from that pack, validates it, and -- only
if validation passes -- writes signal-card.md. SEC and web-search lookups are both
**on by default** (config.toml [research] sec_enabled/web_search_enabled) -- set
either to false to disable it. Web search provider is config.toml [research]
provider ("exa" default, or "tavily"). Tests monkeypatch these flags to false so
they never touch the network.
"""
from __future__ import annotations

import argparse

from dotenv import load_dotenv

from .analysis import cmd_analyze
from .outlook import cmd_validate_outlook
from .prepare import cmd_discover_peers, cmd_prepare
from .review import cmd_check_review, cmd_review_diff


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="earnings", description="Earnings transcript analysis POC")
    sub = parser.add_subparsers(dest="command", required=True)

    discover = sub.add_parser(
        "discover-peers",
        help="Search for the company's analyst peer group (run before prepare; agent picks ~4 --peers)",
    )
    discover.add_argument("--ticker", required=True)
    discover.add_argument(
        "--company-name",
        default=None,
        help="Full company name to sharpen peer-group queries, e.g. 'Microsoft' (defaults to --ticker)",
    )
    discover.add_argument(
        "--event-date",
        default=None,
        help="Optional calendar date, e.g. 2026-07-30. When given, applies the causality "
        "guard as a safety net: dated hits published after it are dropped from extraction; "
        "undated hits still pass through. Omit and no cutoff is applied.",
    )
    discover.set_defaults(func=cmd_discover_peers)

    prep = sub.add_parser("prepare", help="Build a source pack from a transcript")
    prep.add_argument("--ticker", required=True)
    prep.add_argument("--event-id", required=True)
    prep.add_argument("--transcript", required=True, help="Local file path or URL")
    prep.add_argument(
        "--sec-cik",
        default=None,
        help="Numeric SEC CIK, e.g. 320193 (optional -- if omitted, the CIK is "
        "auto-resolved from --ticker via SEC's ticker map unless config.toml disables it)",
    )
    prep.add_argument(
        "--sec-period-end",
        default=None,
        help="XBRL period end date to pin SEC facts to, e.g. 2026-06-30 "
        "(recommended with --sec-cik; without it, the latest-by-end fact is used)",
    )
    prep.add_argument(
        "--sec-period-type",
        default=None,
        choices=["quarter", "half_year", "nine_months", "full_year"],
        help="Duration bucket (derived from each XBRL fact's own start/end dates) to "
        "pin SEC facts to, e.g. 'quarter' -- resolves the case where a 10-Q's 3-month "
        "and 6-month (YTD) facts share the same --sec-period-end. Recommended "
        "alongside --sec-period-end for quarterly figures.",
    )
    prep.add_argument(
        "--company-name",
        default=None,
        help="Full company name for web-search queries, e.g. 'Microsoft' (defaults to --ticker if omitted)",
    )
    prep.add_argument(
        "--event-date",
        default=None,
        help="Calendar date of the earnings event, e.g. 2026-01-28, used to build web-search "
        "queries (defaults to --event-id if omitted, which is usually less precise)",
    )
    prep.add_argument(
        "--peers",
        nargs="*",
        default=[],
        help="The ~4 analyst-recognised peer companies to fetch results for, e.g. --peers "
        "'Amazon AWS' 'Alphabet'. Obtain these by running `earnings discover-peers` first and "
        "reading its candidate pages -- the transcript usually names no competitors. Kept out of "
        "config.toml on purpose: peers are per-company. With none given, only consensus queries run.",
    )
    prep.set_defaults(func=cmd_prepare)

    analyze = sub.add_parser("analyze", help="Validate claims.json and produce signal-card.md")
    analyze.add_argument("--ticker", required=True)
    analyze.add_argument("--event-id", required=True)
    analyze.add_argument("--extractor-model", required=True)
    analyze.add_argument(
        "--extractor-reasoning-effort",
        required=True,
        choices=("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra", "adaptive", "not_applicable", "unknown"),
    )
    analyze.add_argument(
        "--price-decision",
        required=True,
        choices=("used", "not_used", "attempted_failed"),
        help="Whether this extraction used, skipped, or unsuccessfully attempted the price tool",
    )
    analyze.add_argument(
        "--price-reason",
        required=True,
        help="Concise reason for the price-tool decision",
    )
    analyze.set_defaults(func=cmd_analyze)

    validate_outlook = sub.add_parser(
        "validate-outlook", help="Check outlook-brief.md's claim-id citations against validated claims.json"
    )
    validate_outlook.add_argument("--ticker", required=True)
    validate_outlook.add_argument("--event-id", required=True)
    validate_outlook.add_argument("--author-model", required=True)
    validate_outlook.add_argument(
        "--author-reasoning-effort",
        required=True,
        choices=("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra", "adaptive", "not_applicable", "unknown"),
    )
    validate_outlook.set_defaults(func=cmd_validate_outlook)

    check_review = sub.add_parser(
        "check-review",
        help="Validate the outlook-reviewer subagent's review-report.json and render review-report.md",
    )
    check_review.add_argument("--ticker", required=True)
    check_review.add_argument("--event-id", required=True)
    check_review.set_defaults(func=cmd_check_review)

    review_diff = sub.add_parser(
        "review-diff",
        help="Build review-diff.json for a round-2+ diff-based re-review (see cmd_review_diff)",
    )
    review_diff.add_argument("--ticker", required=True)
    review_diff.add_argument("--event-id", required=True)
    review_diff.set_defaults(func=cmd_review_diff)

    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
