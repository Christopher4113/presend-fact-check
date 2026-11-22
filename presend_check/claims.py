from pydantic import BaseModel

from .llm import chat_json
from .models import Claim, ProspectRecord

SYSTEM = """You extract checkable factual claims from a sales outreach email.

A claim is a statement of fact about the prospect person or their company that could be
checked against the company's website: funding round or amount, headcount or team size,
the person's title or role, a product or launch, a named customer, a location, or a news event.

NOT claims: greetings, compliments, opinions, guesses about their pain, facts about the
sender's own company, and the ask or call to action.

Return JSON: {"claims": [{"id": "c1", "text": "...", "kind": "...", "value": "..."}]}
- text: the exact span copied from the draft, word for word.
- kind: one of funding, headcount, title, product, customer, location, news, other.
- value: the normalized fact, short, e.g. "Series A", "$20M", "40 employees", "CTO", "San Francisco".
Return {"claims": []} if there are none."""


class _Claims(BaseModel):
    claims: list[Claim]


def extract_claims(prospect: ProspectRecord, draft: str) -> list[Claim]:
    user = f"Prospect record (may be stale):\n{prospect.model_dump_json(indent=2)}\n\nDraft email:\n{draft}"
    claims = chat_json(SYSTEM, user, _Claims).claims
    # Stable ids regardless of what the model numbered them.
    return [c.model_copy(update={"id": f"c{i}"}) for i, c in enumerate(claims, 1)]
