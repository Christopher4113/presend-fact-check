"""Stretch: run the full pipeline N times on one case and report agreement per claim.

Speaks to PipelineBench's "1 in 10 model/task pairs passed one run and failed the next".
Pages come from the disk cache after run 1, so any disagreement is the model, not the site.
"""

import re
from collections import Counter

from . import check
from .models import ProspectRecord


def _key(kind: str, value: str) -> str:
    return f"{kind}:{re.sub(r'[^a-z0-9]+', ' ', value.lower()).strip()}"


def agreement(runs: list[list[tuple[str, str]]], decisions: list[str]) -> dict:
    """runs: per run, a list of (claim_key, verdict). Pure, for tests and the report."""
    n = len(runs)
    keys = list(dict.fromkeys(k for r in runs for k, _ in r))
    claims = []
    for k in keys:
        seen = [dict(r).get(k, "missing") for r in runs]
        top, count = Counter(seen).most_common(1)[0]
        claims.append({"claim": k, "verdicts": seen, "majority": top, "agreement": f"{count}/{n}",
                       "flaky": len(set(seen)) > 1})
    top_d, count_d = Counter(decisions).most_common(1)[0]
    return {"runs": n, "decisions": decisions, "decision_agreement": f"{count_d}/{n}",
            "decision_flaky": len(set(decisions)) > 1, "claims": claims}


def run_consistency(prospect: ProspectRecord, draft: str, n: int = 5) -> dict:
    """Claims are matched across runs by where they sit in the draft (overlapping spans), not by
    the extractor's wording, which drifts ("$355M" vs "$355M Series C") even at temperature 0."""
    spans: list[tuple[int, int, str]] = []  # canonical (start, end, label)

    def key(c) -> str:
        at = draft.find(c.text)
        if at < 0:
            return _key(c.kind, c.value)
        end = at + len(c.text)
        for s0, s1, label in spans:
            if at < s1 and s0 < end:
                return label
        spans.append((at, end, f'"{c.text}"'))
        return spans[-1][2]

    runs, decisions = [], []
    for _ in range(n):
        r = check(prospect, draft)
        by_id = {c.id: c for c in r.claims}
        runs.append([(key(by_id[v.claim_id]), v.verdict) for v in r.verdicts])
        decisions.append(r.decision)
    return agreement(runs, decisions)
