"""Central place for tunables: env var names, base URLs, size limits, paths.

User-tunable knobs (timeouts, segmentation markers, validation tolerances, SEC
concepts) are loaded from `config.toml` at the repo root via stdlib `tomllib`, with
the built-in defaults below used for any key that is absent. Structural values that
would break the skills if changed (env-var names, endpoint URLs, output layout) stay
hardcoded here on purpose. No secrets live here -- only names of env vars.
"""
from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

# config.toml sits at the repo root (this file is src/earnings/config.py).
_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.toml"


def _load_toml() -> dict[str, Any]:
    if _CONFIG_PATH.is_file():
        with _CONFIG_PATH.open("rb") as fh:
            return tomllib.load(fh)
    return {}


_CFG = _load_toml()


def _get(section: str, key: str, default: Any) -> Any:
    """Fetch config.toml[section][key], falling back to the built-in default."""
    return _CFG.get(section, {}).get(key, default)


def _validate_provider(name: str) -> str:
    """Fail fast on a typo'd provider name instead of silently falling through to Tavily."""
    if name not in ("exa", "tavily"):
        raise ValueError(f"Unknown research provider {name!r}; expected 'exa' or 'tavily'")
    return name


# --- Env var names (values loaded via python-dotenv / os.environ at call sites) ---
TAVILY_API_KEY_ENV = "TAVILY_API_KEY"
EXA_API_KEY_ENV = "EXA_API_KEY"
SEC_USER_AGENT_ENV = "SEC_USER_AGENT"

# --- Output layout (structural: changing these breaks the skills) ---
RUNS_DIR = Path("runs")
RAW_SUBDIR = "raw"
NORMALIZED_SUBDIR = "normalized"
EVIDENCE_SUBDIR = "evidence"
ARCHIVE_SUBDIR = "_archive"  # a prior run's files, moved here (timestamped) instead of overwritten
REVIEW_HISTORY_SUBDIR = "_review_history"  # per-round snapshots of claims.json/outlook-brief.md/review-report.json, for diffing
VALIDATION_HISTORY_SUBDIR = "_validation_history"  # append-only snapshots of every deterministic analyze attempt
MANIFEST_FILENAME = "manifest.json"
TRANSCRIPT_FILENAME = "transcript.jsonl"
FINANCIALS_FILENAME = "financials.json"
CLAIMS_FILENAME = "claims.json"
METRICS_FILENAME = "metrics.json"  # optional: agent-authored, discovered per company (see models.Metric)
WEB_SUBDIR = "web"  # under evidence/: extracted Tavily content, one .md per WebEvidence
WEB_EVIDENCE_FILENAME = "web-evidence.jsonl"  # under evidence/
VALIDATION_FILENAME = "validation.json"
VALIDATION_ATTEMPT_RECEIPT_FILENAME = "receipt.json"
INJECTION_SCAN_FILENAME = "injection-scan.json"  # advisory prompt-injection flag results (see process.scan_for_injection)
SIGNAL_CARD_FILENAME = "signal-card.md"
OUTLOOK_BRIEF_FILENAME = "outlook-brief.md"
OUTLOOK_VALIDATION_FILENAME = "outlook-validation.json"  # Python-owned: real-clock stamp for validate-outlook
REVIEW_REPORT_JSON_FILENAME = "review-report.json"  # agent-authored (Outlook_Reviewer subagent)
REVIEW_REPORT_MD_FILENAME = "review-report.md"  # Python-rendered from the JSON above
REVIEW_DIFF_FILENAME = "review-diff.json"  # Python-authored context for every review after round 1

# --- Cross-run processing log (repo root, not per-run -- see cli._append_processing_log) ---
LOGS_DIR = Path("logs")
PROCESSING_LOG_FILENAME = "processing_log.jsonl"

# --- SEC endpoints (data.sec.gov requires a compliant identifying User-Agent) ---
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
SEC_COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SEC_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"

# --- Tavily endpoints ---
TAVILY_SEARCH_URL = "https://api.tavily.com/search"
TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"

# --- Exa endpoints ---
EXA_SEARCH_URL = "https://api.exa.ai/search"
EXA_CONTENTS_URL = "https://api.exa.ai/contents"

# --- Size / safety limits (config.toml [http]) ---
HTTP_TIMEOUT_SECONDS = float(_get("http", "timeout_seconds", 20.0))
MAX_FETCH_BYTES = int(_get("http", "max_fetch_mb", 10)) * 1024 * 1024

# --- Segmentation heuristics (config.toml [segmentation]) ---
QA_BOUNDARY_MARKERS = tuple(
    _get(
        "segmentation",
        "qa_boundary_markers",
        [
            "questions and answers",
            "question-and-answer",
            "q&a",
            "we will now begin the question-and-answer session",
            "operator instructions",
        ],
    )
)
SEGMENT_ID_PREFIX = "seg"
SEGMENT_ID_WIDTH = 4

# --- Prompt-injection flag (config.toml [sanitisation]) ---
# Best-effort regex FLAG over the sanitised transcript -- not a classifier, not a gate.
# Toggle off if noisy; patterns live in config so the list can grow without code changes.
SANITISATION_INJECTION_SCAN_ENABLED = bool(_get("sanitisation", "injection_scan_enabled", True))
SANITISATION_INJECTION_PATTERNS = list(_get("sanitisation", "injection_patterns", []))

# --- PDF ingestion (config.toml [pdf_ingestion]) ---
PDF_FACTSET_REFORMAT_ENABLED = bool(_get("pdf_ingestion", "factset_reformat_enabled", True))
PDF_FACTSET_SEPARATOR_PATTERN = str(_get("pdf_ingestion", "factset_separator_pattern", r"^[.]{10,}\s*$"))
PDF_FACTSET_BANNER_PATTERNS = list(_get("pdf_ingestion", "factset_banner_patterns", []))

# --- Validation tolerances (config.toml [validation]) ---
CALC_RELATIVE_TOLERANCE = float(_get("validation", "calc_relative_tolerance", 0.01))
CALC_ABSOLUTE_TOLERANCE = float(_get("validation", "calc_absolute_tolerance", 0.005))
NUMERIC_MATCH_TOLERANCE = float(_get("validation", "numeric_match_tolerance", 1e-6))

# --- Review rounds (config.toml [review]) ---
REVIEW_MAX_ROUNDS = int(_get("review", "max_review_rounds", 3))
REVIEW_DIFF_MAX_CLAIMS_CHANGED = int(_get("review", "diff_review_max_claims_changed", 3))
REVIEW_DIFF_CONCLUSION_SECTIONS = list(_get("review", "diff_review_conclusion_sections", [1, 5, 6, 7]))

# --- SEC data pull (config.toml [sec]) ---
SEC_CONCEPTS = list(_get("sec", "concepts", ["Revenues", "NetIncomeLoss", "EarningsPerShareDiluted"]))
SEC_DEFAULT_USER_AGENT = str(_get("sec", "default_user_agent", "earnings-poc unset@example.com"))
SEC_RESOLVE_CIK_FROM_TICKER = bool(_get("sec", "resolve_cik_from_ticker", True))
SEC_REQUIRE_PERIOD_MATCH = bool(_get("sec", "require_period_match", True))
SEC_FORMS = list(_get("sec", "forms", ["8-K", "10-Q", "10-K", "20-F", "6-K"]))

# --- Research toggles (config.toml [research]) ---
RESEARCH_SEC_ENABLED = bool(_get("research", "sec_enabled", True))
RESEARCH_WEB_SEARCH_ENABLED = bool(_get("research", "web_search_enabled", True))
RESEARCH_WEB_SEARCH_PROVIDER = _validate_provider(str(_get("research", "provider", "exa")))  # "exa" | "tavily"
RESEARCH_OFFICIAL_SOURCES_ONLY = bool(_get("research", "official_sources_only", True))
RESEARCH_ARCHIVE_ALL_SOURCES = bool(_get("research", "archive_all_sources", True))
RESEARCH_INCLUDE_PREVIOUS_PERIOD = bool(_get("research", "include_previous_period", True))
# Repurposed web search: query templates for info NOT already in the transcript --
# analyst consensus/expectations and peer-group results. {company}/{ticker}/{event_id}
# are filled per run; peer templates also fill {peer} (peers come from --peers). Empty
# a list to disable that class. See sources.build_consensus_queries/build_peer_queries.
RESEARCH_CONSENSUS_QUERIES = list(
    _get(
        "research",
        "consensus_queries",
        [
            "{company} {ticker} {event_id} analyst consensus estimate revenue EPS",
            "{company} {ticker} {event_id} earnings preview expectations forecast",
            "{company} {ticker} Wall Street consensus estimates ahead of earnings",
        ],
    )
)
RESEARCH_PEER_QUERIES = list(
    _get(
        "research",
        "peer_queries",
        [
            "{peer} {event_id} earnings results revenue growth",
            "{peer} quarterly results versus {company} {ticker}",
        ],
    )
)
# Peer-group DISCOVERY templates (earnings discover-peers, run before prepare) -- find
# the company's analyst-recognised comparables to select ~4 peers from. See
# sources.build_peer_group_queries.
RESEARCH_PEER_GROUP_QUERIES = list(
    _get(
        "research",
        "peer_group_queries",
        [
            "{company} {ticker} peer group comparable companies",
            "{company} {ticker} closest competitors comparable stocks analysts",
            "stocks most similar to {ticker} {company}",
        ],
    )
)

# --- Tavily defaults (config.toml [tavily]), used when research.provider == "tavily" ---
TAVILY_SEARCH_DEPTH = str(_get("tavily", "search_depth", "basic"))
TAVILY_MAX_RESULTS = int(_get("tavily", "max_results", 5))
TAVILY_INCLUDE_EXTERNAL_COMMENTARY = bool(_get("tavily", "include_external_commentary", False))
TAVILY_INCLUDE_ANSWER = bool(_get("tavily", "include_answer", False))
TAVILY_INCLUDE_RAW_CONTENT = bool(_get("tavily", "include_raw_content", False))
TAVILY_EXTRACT_DEPTH = str(_get("tavily", "extract_depth", "basic"))
TAVILY_MAX_EXTRACTED_SOURCES = int(_get("tavily", "max_extracted_sources", 10))

# --- Exa defaults (config.toml [exa]), used when research.provider == "exa" (default) ---
EXA_TYPE = str(_get("exa", "type", "auto"))
EXA_NUM_RESULTS = int(_get("exa", "num_results", 5))
EXA_MAX_EXTRACTED_SOURCES = int(_get("exa", "max_extracted_sources", 10))

# --- Invisible / zero-width unicode code points stripped during sanitisation ---
ZERO_WIDTH_CHARS = (
    "​",  # zero width space
    "‌",  # zero width non-joiner
    "‍",  # zero width joiner
    "﻿",  # BOM / zero width no-break space
    "‎",  # left-to-right mark
    "‏",  # right-to-left mark
    "­",  # soft hyphen
)


def sec_user_agent() -> str:
    """Return the SEC-compliant User-Agent from env, or the configured placeholder."""
    return os.environ.get(SEC_USER_AGENT_ENV, SEC_DEFAULT_USER_AGENT)


def tavily_api_key() -> str | None:
    return os.environ.get(TAVILY_API_KEY_ENV)


def exa_api_key() -> str | None:
    return os.environ.get(EXA_API_KEY_ENV)


def run_dir(ticker: str, event_id: str) -> Path:
    return RUNS_DIR / ticker.upper() / event_id
