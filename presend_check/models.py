from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

ClaimKind = Literal["funding", "headcount", "title", "product", "customer", "location", "news", "other"]
Verdict = Literal["supported", "stale", "unverified"]
Decision = Literal["PASS", "REVIEW", "BLOCK"]


class ProspectRecord(BaseModel):
    person_name: str
    person_title: str | None = None
    company: str
    domain: str  # "acme.com"
    headcount: int | None = None
    funding_stage: str | None = None  # "Seed", "Series A", ...
    last_enriched: date | None = None  # how old the CRM data is


class Claim(BaseModel):
    id: str
    text: str  # exact span from the draft: "congrats on the Series A"
    kind: ClaimKind
    value: str  # normalized value: "Series A"


class Evidence(BaseModel):
    """One chunk of a company page, ~800 chars, with the URL it came from."""

    url: str
    text: str
    score: float = 0.0


class ClaimVerdict(BaseModel):
    claim_id: str
    verdict: Verdict
    corrected_value: str | None = None  # "Series B" when stale
    source_url: str | None = None
    quote: str | None = None  # <= 25 words from the page
    reason: str


class CheckResult(BaseModel):
    decision: Decision
    claims: list[Claim] = Field(default_factory=list)
    verdicts: list[ClaimVerdict]
    fixed_draft: str | None = None
    fixed_check: CheckResult | None = None  # re-verification of fixed_draft
    pages_checked: list[str]
    latency_ms: int
