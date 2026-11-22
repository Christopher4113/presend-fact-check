from .models import Claim, ClaimVerdict, Decision

# Unverified claims of these kinds go to a person; the rest are low risk.
REVIEW_KINDS = {"funding", "headcount", "title"}


def decide(claims: list[Claim], verdicts: list[ClaimVerdict]) -> Decision:
    """Any stale -> BLOCK. Unverified funding/headcount/title -> REVIEW. Else PASS."""
    kinds = {c.id: c.kind for c in claims}
    if any(v.verdict == "stale" for v in verdicts):
        return "BLOCK"
    if any(v.verdict == "unverified" and kinds.get(v.claim_id) in REVIEW_KINDS for v in verdicts):
        return "REVIEW"
    return "PASS"
