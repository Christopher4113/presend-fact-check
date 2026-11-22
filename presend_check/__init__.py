"""Pre-send fact checker: check(prospect, draft) -> CheckResult."""

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from .claims import extract_claims
from .decide import decide
from .evidence import gather_evidence, headlines, top_chunks, top_headlines
from .fix import fix_draft
from .models import CheckResult, Claim, ClaimVerdict, Evidence, ProspectRecord
from .verify import verify_claim

Event = Callable[[dict], None]


def _verify_all(claims: list[Claim], chunks: list[Evidence], heads: list[Evidence], emit: Event) -> list[ClaimVerdict]:
    def one(c: Claim) -> ClaimVerdict:
        t = time.perf_counter()
        v = verify_claim(c, top_chunks(c, chunks), top_headlines(c, heads))
        emit({"type": "verdict", "claim": c.model_dump(), "verdict": v.model_dump(),
              "ms": int((time.perf_counter() - t) * 1000)})
        return v
    with ThreadPoolExecutor(max_workers=2) as pool:  # ponytail: rate-limit bound, raise on a paid tier
        return list(pool.map(one, claims))


def check(prospect: ProspectRecord, draft: str, fix: bool = False, fresh: bool = False,
          on_event: Event | None = None, _chunks: tuple | None = None) -> CheckResult:
    emit = on_event or (lambda e: None)
    t0 = time.perf_counter()

    # 1 + 2 run in parallel: claim extraction (LLM) and fetching the site (network).
    with ThreadPoolExecutor(max_workers=2) as pool:
        emit({"type": "step", "step": "extract_claims"})
        fut_claims = pool.submit(extract_claims, prospect, draft)
        if _chunks is None:
            emit({"type": "step", "step": "gather_evidence", "domain": prospect.domain})
            fut_pages = pool.submit(gather_evidence, prospect.domain, fresh,
                                    lambda url, ok: emit({"type": "page", "url": url, "ok": ok}))
        claims = fut_claims.result()
        emit({"type": "claims", "claims": [c.model_dump() for c in claims]})
        pages, chunks = _chunks if _chunks is not None else fut_pages.result()

    # 3 verify, 4 decide
    emit({"type": "step", "step": "verify_claims"})
    verdicts = _verify_all(claims, chunks, headlines(pages), emit)
    decision = decide(claims, verdicts)
    result = CheckResult(decision=decision, claims=claims, verdicts=verdicts,
                         pages_checked=[p.url for p in pages], latency_ms=0)

    # 5 optional minimal rewrite, then re-check against the same evidence
    if fix and decision == "BLOCK":
        emit({"type": "step", "step": "fix_draft"})
        result.fixed_draft = fix_draft(draft, claims, verdicts)
        if result.fixed_draft:
            emit({"type": "fixed_draft", "draft": result.fixed_draft})
            result.fixed_check = check(prospect, result.fixed_draft, _chunks=(pages, chunks))

    result.latency_ms = int((time.perf_counter() - t0) * 1000)
    emit({"type": "result", "result": result.model_dump(mode="json")})
    return result


__all__ = ["check", "CheckResult", "ProspectRecord", "Claim", "ClaimVerdict"]
