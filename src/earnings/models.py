"""Minimal Pydantic v2 schemas shared across the pipeline."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Section = Literal["prepared", "qa"]
ClaimStatus = Literal["reported", "forward_looking"]

# Generic evidence categories -- deliberately industry-agnostic. No category names a
# sector-specific metric (e.g. no "cloud_revenue" or "same_store_sales"); those live in
# claim_text/values/Metric instead, discovered per company rather than hardcoded per category.
ClaimCategory = Literal[
    "reported_financial_performance",
    "operational_performance",
    "current_guidance",
    "guidance_change",
    "demand_activity",
    "pricing_volume_mix",
    "costs_margins_efficiency",
    "capacity_supply_execution",
    "cash_flow_capital_allocation",
    "balance_sheet_solvency",
    "regulatory_legal_macro",
    "management_explanation",
    "qa_insight",
    "risk",
]

# How the claim relates to the source -- distinct from ClaimCategory (what it's about)
# and ClaimStatus (reported vs forward-looking).
ClaimClassification = Literal[
    "reported_fact", "management_guidance", "management_opinion", "analyst_question", "analytical_inference"
]


class Segment(BaseModel):
    id: str
    section: Section
    speaker: Optional[str] = None
    text: str  # already canonically whitespace-normalized (see process.normalize_whitespace)


class WebEvidence(BaseModel):
    """One piece of full-text content extracted (not just search-snippet'd) via
    Tavily's /extract endpoint, so a claim can cite and quote-check against it the
    same way it cites a transcript segment. A raw Tavily search hit is NOT
    WebEvidence -- see cli.cmd_prepare's extraction step.
    """

    id: str  # e.g. "web-001"
    url: str
    title: Optional[str] = None
    publisher: Optional[str] = None
    published_at: Optional[str] = None
    retrieved_at: str  # ISO 8601 UTC timestamp
    content_path: str  # path relative to the run directory, e.g. evidence/web/web-001.md
    content_sha256: str


class SourceRecord(BaseModel):
    """One archived source (a transcript file, a SEC filing, a Tavily result, ...)."""

    path: str  # path relative to the run directory, e.g. raw/transcript.txt
    origin: str  # original url or local path the content came from
    retrieved_at: str  # ISO 8601 UTC timestamp
    content_type: str
    sha256: str
    byte_length: int


class Manifest(BaseModel):
    ticker: str
    event_id: str
    created_at: str  # ISO 8601 UTC timestamp
    sources: list[SourceRecord] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class Claim(BaseModel):
    id: Optional[str] = None  # e.g. "claim-012"; set by the agent so Metric/outlook-brief can cite it
    category: ClaimCategory
    classification: ClaimClassification
    claim_text: str
    quote: str
    # Exactly one of these two must be set -- a claim cites either a transcript
    # segment or a piece of extracted web evidence, never both/neither. Not modeled
    # as a Pydantic discriminated union so validate.check_evidence_reference can give
    # an explicit, testable error message instead of a generic schema failure.
    segment_id: Optional[str] = None
    web_evidence_id: Optional[str] = None
    speaker: Optional[str] = None
    status: ClaimStatus
    values: dict = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)
    # Required (non-empty) when classification == "analytical_inference": the claim ids
    # this inference was derived from. See validate.check_inference_citations.
    inferred_from: list[str] = Field(default_factory=list)


class Metric(BaseModel):
    """A company-defined metric discovered from disclosures, not a fixed sector KPI
    list. Every metric traces to the claim(s) it came from -- no metric may exist
    without a source_claim_ids entry pointing at a validated Claim.id.
    """

    name: str
    value: float
    unit: str  # the unit as the company itself reported it, e.g. "USD millions", "%", "units"
    period: str  # the reported period, e.g. "Q2 FY2026"
    # Provenance marker. metrics.json is always agent-authored (Python has no metric
    # generator) -- unlike evidence/financials.json, which is self-documenting via its
    # own "form"/"fy"/"filed"/"accn" fields because Python fetched it directly from SEC.
    source: str = "agent_derived_from_transcript"
    definition: str  # definition taken verbatim/paraphrased from the source, not assumed
    source_claim_ids: list[str] = Field(default_factory=list)


class ValidationIssue(BaseModel):
    claim_index: int
    check: str  # e.g. "exact_quote", "numeric", "calculation", "schema"
    message: str


class ValidationResult(BaseModel):
    ok: bool
    checked_claims: int
    issues: list[ValidationIssue] = Field(default_factory=list)


# Final semantic-audit stage (Outlook_Reviewer subagent, Opus). Judges what
# deterministic Python cannot: fair-reading of quotes, narrative balance, omissions.
# Never re-derives hashes/citation/numeric checks -- validation.json.ok already
# proves those (see .claude/agents/outlook-reviewer.md).
ReviewVerdict = Literal["pass", "pass_with_warnings", "fail"]
FindingSeverity = Literal["info", "low", "medium", "high", "critical"]


class ReviewFinding(BaseModel):
    severity: FindingSeverity
    artifact: str  # e.g. "outlook-brief.md" or "claims.json#claim-007"
    passage: str  # exact quoted passage the finding concerns
    evidence: str  # what supports or contradicts it
    recommendation: str


class ReviewReport(BaseModel):
    """Agent-authored (Outlook_Reviewer writes this JSON only, never the .md --
    see cli.cmd_check_review, which renders review-report.md deterministically from
    this validated structure, same pattern as signal-card.md from claims.json).
    """

    verdict: ReviewVerdict
    reviewed_at: str  # ISO 8601 UTC timestamp
    model: str = "opus"
    source_checks: list[ReviewFinding] = Field(default_factory=list)
    claim_findings: list[ReviewFinding] = Field(default_factory=list)
    outlook_findings: list[ReviewFinding] = Field(default_factory=list)
    process_findings: list[ReviewFinding] = Field(default_factory=list)
    unverified_items: list[str] = Field(default_factory=list)
    summary: str
