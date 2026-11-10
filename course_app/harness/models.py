"""
Model bindings and measured calls.

The writer and the judge are different model families,
so the checker is never the author. Every call returns its real usage, so the game
can show measured prompt sizes and cost.
"""

import json
import re
import time
import urllib.request
from dataclasses import asdict, dataclass

import streamlit as st

from core import llm

WRITER = "openai/gpt-6-luna"       # writes notices and tracks the shipment state
JUDGE = "anthropic/claude-haiku-5.5"   # ranks and verifies: never the model that wrote

try:
    import tiktoken
    _ENC = tiktoken.get_encoding("o200k_base")
except Exception:  # pragma: no cover - tokenizer download unavailable
    _ENC = None


def count_tokens(text: str) -> int:
    """Tokens of a text that isn't sent to a model (previews). Live calls use the provider's own count."""
    if _ENC is None:
        return max(1, len(text) // 4)
    return len(_ENC.encode(text))


@dataclass
class Usage:
    model: str
    prompt_tokens: int
    completion_tokens: int
    seconds: float
    cost_usd: float | None
    reasoning_tokens: int = 0     # part of completion_tokens the model spent thinking before answering
    finish_reason: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@st.cache_resource(ttl=6 * 3600)
def _prices() -> dict:
    """USD per token for our two models, from OpenRouter's public model list."""
    try:
        data = json.loads(urllib.request.urlopen("https://openrouter.ai/api/v1/models", timeout=15).read())["data"]
        return {m["id"]: (float(m["pricing"]["prompt"]), float(m["pricing"]["completion"]))
                for m in data if m["id"] in (WRITER, JUDGE)}
    except Exception:
        return {}


def cost_of(model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    price = _prices().get(model)
    if not price:
        return None
    return prompt_tokens * price[0] + completion_tokens * price[1]


def extract_json(text: str) -> dict:
    """The first JSON object in a reply, tolerating code fences and prose around it."""
    t = (text or "").strip()
    t = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    start = t.find("{")
    if start < 0:
        raise ValueError(f"No JSON object in the reply: {t[:200]!r}")
    depth, in_str, esc = 0, False, False
    for i in range(start, len(t)):
        ch = t[i]
        if in_str:
            esc = (ch == "\\") and not esc
            if ch == '"' and not esc:
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(t[start:i + 1])
    raise ValueError("The JSON object in the reply is not closed")


def call_json(model: str, system: str, user: str, max_tokens: int = 800) -> tuple[dict, Usage, str]:
    """
    One live call that must return a JSON object. Returns (data, usage, raw text).
    Raises on transport errors or unparseable output; callers decide how to recover.
    """
    start = time.time()
    response = llm.client().chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        response_format={"type": "json_object"},
        max_tokens=max_tokens,
    )
    raw = response.choices[0].message.content or ""
    usage = response.usage
    prompt_tokens = getattr(usage, "prompt_tokens", None) or count_tokens(system + user)
    completion_tokens = getattr(usage, "completion_tokens", None) or count_tokens(raw)
    # OpenRouter reports the actual charge on the usage object; the price table is only the fallback.
    reported = getattr(usage, "cost", None)
    details = getattr(usage, "completion_tokens_details", None)
    reasoning = int(getattr(details, "reasoning_tokens", 0) or 0)
    u = Usage(model, prompt_tokens, completion_tokens, round(time.time() - start, 1),
              float(reported) if reported is not None else cost_of(model, prompt_tokens, completion_tokens),
              reasoning, response.choices[0].finish_reason or "")
    if not raw.strip():
        raise ValueError(f"Empty reply after {completion_tokens} completion tokens "
                         f"({reasoning} spent reasoning, finish_reason={u.finish_reason})")
    return extract_json(raw), u, raw
