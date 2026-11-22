"""chat_json(system, user, schema) -> validated pydantic object.

LLM_PROVIDER=groq (default): Groq through the OpenAI SDK, JSON mode, temperature 0, one retry on a schema error.
LLM_PROVIDER=anthropic: Claude through the Anthropic SDK with structured outputs (messages.parse), so the
response is schema-valid by construction. Key from ANTHROPIC_API_KEY or ANTHROPIC_KEY; model from
ANTHROPIC_MODEL (default claude-opus-5-5), effort from ANTHROPIC_EFFORT (default low: these are short,
well-specified extraction/judging calls, and the demo wants latency).
"""

import json
import os
from functools import lru_cache
from typing import TypeVar

from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

load_dotenv()


def provider() -> str:
    return os.environ.get("LLM_PROVIDER", "groq").lower()


# ---------- Groq (OpenAI-compatible) ----------

@lru_cache(maxsize=1)
def _groq():
    from openai import OpenAI
    return OpenAI(api_key=os.environ["GROQ_API_KEY"], base_url="https://api.groq.com/openai/v1",
                  max_retries=10)  # free tier is 8k tokens/min; SDK backs off on 429


def _groq_json(system: str, user: str, schema: type[T]) -> T:
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    for attempt in range(2):
        resp = _groq().chat.completions.create(
            model=os.environ["GROQ_MODEL"],
            messages=messages,
            temperature=0,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or ""
        try:
            return schema.model_validate(json.loads(raw))
        except (ValidationError, json.JSONDecodeError) as e:
            if attempt == 1:
                raise
            messages += [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": f"That JSON failed validation:\n{e}\nReturn corrected JSON only."},
            ]
    raise AssertionError("unreachable")


# ---------- Anthropic ----------

@lru_cache(maxsize=1)
def _anthropic():
    import anthropic
    return anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY") or os.environ["ANTHROPIC_KEY"],
                               max_retries=4)


def _anthropic_json(system: str, user: str, schema: type[T]) -> T:
    resp = _anthropic().beta.messages.parse(
        model=os.environ.get("ANTHROPIC_MODEL", "claude-opus-5-5"),
        max_tokens=16000,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_format=schema,
        output_config={"effort": os.environ.get("ANTHROPIC_EFFORT", "low")},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",  # a safety decline is re-run on a fallback model inside the same call
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError(f"Claude declined: {resp.stop_details}")
    if resp.parsed_output is None:
        raise RuntimeError(f"No structured output (stop_reason={resp.stop_reason})")
    return resp.parsed_output


def chat_json(system: str, user: str, schema: type[T]) -> T:
    return _anthropic_json(system, user, schema) if provider() == "anthropic" else _groq_json(system, user, schema)
