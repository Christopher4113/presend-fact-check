from pydantic import BaseModel

from .llm import chat_json
from .models import Claim, ClaimVerdict

SYSTEM = """You edit a sales email with the smallest possible change.
Replace ONLY the listed stale facts with their corrected values. Keep every other word,
punctuation mark and line break exactly as it is. Adjust only the minimum grammar the
replacement forces (e.g. "a" -> "an").
Return JSON: {"draft": "..."}"""


class _Fixed(BaseModel):
    draft: str


def fix_draft(draft: str, claims: list[Claim], verdicts: list[ClaimVerdict]) -> str | None:
    by_id = {c.id: c for c in claims}
    stale = [(by_id[v.claim_id], v) for v in verdicts if v.verdict == "stale" and v.claim_id in by_id]
    if not stale:
        return None
    fixes = "\n".join(f'- span "{c.text}": "{c.value}" is stale, correct value is "{v.corrected_value}"'
                      f' (the site says: "{v.quote}"). Every part of the span that the site contradicts must change.'
                      for c, v in stale)
    return chat_json(SYSTEM, f"Email:\n{draft}\n\nStale facts to fix:\n{fixes}", _Fixed).draft
