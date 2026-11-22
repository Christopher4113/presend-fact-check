import re
from datetime import date

from pydantic import BaseModel

from .llm import chat_json
from .models import Claim, ClaimVerdict, Evidence, Verdict

SYSTEM = """You are a strict fact checker for a sales email. You see ONE claim and a few
excerpts from the prospect company's own website. Judge the claim using ONLY those excerpts.

- "supported": an excerpt clearly states the claimed fact.
- "stale": an excerpt clearly states something DIFFERENT and MORE RECENT that replaces the
  claim (e.g. claim says Series A, site announces a Series B; claim says 20 people, site says 80).
  Put the up-to-date value in corrected_value.
- "unverified": the excerpts do not say either way. NEVER guess. Absence of evidence is
  unverified, not stale.

Company sites keep old announcements online. An excerpt confirming that the claimed event
happened is NOT enough for "supported" when the email presents it as the current state
("congrats on the Series B", "your 40-person team"):
- First scan ALL excerpts for a later value (a later round letter, a bigger or newer number,
  a newer title). If one exists, the verdict is "stale", even if another excerpt confirms the
  old value, and even if the old value is not mentioned at all.
- Only say "supported" if no excerpt shows a more recent value for the same fact.
For stale, the quote must be the excerpt that states the NEWER value.
For stale, corrected_value must replace the claim's normalized value IN FULL, in the same shape:
claim "$355M Series C" -> "$750M Series D" (amount AND round), claim "40 employees" -> "120 employees".
- Same fact only. A claim that names part of a list the site gives in full ("offices in NY and SF",
  site lists NY, SF and London) is supported, not stale. Stale means the claimed value was replaced.

Rules:
- quote: copy 25 words or fewer WORD FOR WORD from one excerpt (exact characters, no edits,
  no ellipses). Required for supported and stale. null when unverified.
- source_url: the URL of the excerpt the quote came from.
- reason: one short sentence.

Return JSON: {"verdict": "...", "corrected_value": "..." or null, "source_url": "..." or null,
"quote": "..." or null, "reason": "..."}"""


class _Judgement(BaseModel):
    verdict: Verdict
    corrected_value: str | None = None
    source_url: str | None = None
    quote: str | None = None
    reason: str


def _norm(s: str) -> str:
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("–", "-").replace("—", "-").replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip().lower()


def enforce_quote(v: ClaimVerdict, chunks: list[Evidence]) -> ClaimVerdict:
    """A supported/stale verdict must quote a chunk verbatim; otherwise it becomes unverified.

    Whitespace, case and curly quotes are normalized; nothing else is forgiven.
    """
    if v.verdict == "unverified":
        return v
    q = _norm(v.quote or "").strip(" .,;:!?\"'")  # boundary punctuation only
    source = next((c for c in chunks if q and q in _norm(c.text)), None)
    if source is None:
        return v.model_copy(update={
            "verdict": "unverified", "corrected_value": None,
            "reason": f"Quote not found verbatim in the evidence (was {v.verdict}). {v.reason}"})
    return v.model_copy(update={"source_url": source.url})


ROUNDS = ["pre-seed", "seed", "series a", "series b", "series c", "series d", "series e",
          "series f", "series g", "series h"]
_ROUND_RE = re.compile(r"\b(pre-seed|seed|series [a-h])\b", re.I)


def _round(text: str) -> int | None:
    """Index of the latest round named in text, e.g. 'raises $50m Series C' -> 4."""
    found = [ROUNDS.index(m.lower()) for m in _ROUND_RE.findall(text)]
    return max(found) if found else None


def later_round_guard(claim: Claim, v: ClaimVerdict, heads: list[Evidence]) -> ClaimVerdict:
    """Deterministic backstop: a funding claim can't be 'supported' when a page headline on
    the same site announces a later round. The judge sometimes misses this; code doesn't."""
    if claim.kind != "funding" or v.verdict != "supported" or (mine := _round(claim.value)) is None:
        return v
    later = [(r, h) for h in heads if (r := _round(h.text)) is not None and r > mine]
    if not later:
        return v
    r, h = max(later, key=lambda x: x[0])
    quote = next(ln for ln in h.text.splitlines() if _ROUND_RE.search(ln))
    amount = re.search(r"(\$[\d.,]+\s?(?:[mbk]|million|billion)?)\s+(?:in\s+)?" + ROUNDS[r], quote, re.I)
    corrected = f"{amount.group(1)} {ROUNDS[r].title()}" if amount else ROUNDS[r].title()
    return ClaimVerdict(claim_id=v.claim_id, verdict="stale", corrected_value=corrected,
                        source_url=h.url, quote=quote,
                        reason=f"The site announces a later round ({ROUNDS[r].title()}) than the claim.")


def verify_claim(claim: Claim, chunks: list[Evidence], heads: list[Evidence] = (),
                 today: date | None = None) -> ClaimVerdict:
    chunks = list(chunks) + list(heads)
    if not chunks:
        return ClaimVerdict(claim_id=claim.id, verdict="unverified",
                            reason="No relevant text found on the company site.")
    body = chunks[:len(chunks) - len(heads)]
    excerpts = "\n\n".join(f"[{i}] {c.url}\n{c.text}" for i, c in enumerate(body, 1))
    user = (f"Today is {(today or date.today()).isoformat()}.\n\n"
            f"Claim ({claim.kind}): \"{claim.text}\"\nNormalized value: {claim.value}\n\n"
            f"Website excerpts:\n{excerpts}")
    if heads:
        user += ("\n\nEvery announcement headline on the site for this kind of fact (one per page). "
                 "Funding rounds go pre-seed < seed < Series A < B < C < D < E < F; if any headline "
                 "names a later round than the claim, the claim is stale:\n"
                 + "\n".join(f"- {h.url}\n  {h.text}" for h in heads))
    j = chat_json(SYSTEM, user, _Judgement)
    v = ClaimVerdict(claim_id=claim.id, **j.model_dump())
    return later_round_guard(claim, enforce_quote(v, chunks), list(heads))
