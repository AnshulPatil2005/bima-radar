"""Stage 2b · Gemini extractor for text the rules cannot explain (an unusual SMS, a policy paragraph).

Two guards keep it honest:
  1. Every cover must quote its evidence, and the quote must appear in the input text.
  2. Amounts for known schemes come from schemes.py, not from the model.
Calls the Gemini REST API with the standard library. Without a GEMINI_API_KEY the pipeline runs on rules alone.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from bima_radar import schemes
from bima_radar.models import Cover, Evidence

MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MAX_CHARS = 60_000

TYPES = ["pmsby", "pmjjby", "rupay_pmjdy", "loan_protection", "irctc_travel", "card_air_accident", "employer_health", "other"]

SCHEMA = {
    "type": "object",
    "properties": {
        "covers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": TYPES},
                    "name": {"type": "string"},
                    "sum_insured_inr": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                    "what_it_pays": {"type": "string"},
                    "conditions": {"type": "array", "items": {"type": "string"}},
                    "evidence_quote": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["type", "name", "sum_insured_inr", "what_it_pays", "conditions", "evidence_quote", "confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["covers"],
    "additionalProperties": False,
}

SYSTEM = """You find insurance cover hidden in Indian bank SMS, account statements, loan papers, tickets and policy text.
Report only cover that the text states or clearly implies: a PMSBY or PMJJBY premium debit, a loan protection or credit shield premium, travel insurance opted on a ticket, accident cover on a Jan Dhan RuPay card, an insurance premium line, an employer health plan.
evidence_quote must be copied exactly from the text, word for word. If you cannot quote it, leave the cover out.
Set sum_insured_inr only when the text states the amount; otherwise null.
Write what_it_pays and conditions in short, plain English for someone who has never bought insurance, and only say what the text supports.
If the text holds no cover, return an empty list."""

KIND = {"pmsby": "Accident", "pmjjby": "Life", "rupay_pmjdy": "Accident", "loan_protection": "Loan", "irctc_travel": "Travel",
        "card_air_accident": "Accident", "employer_health": "Health", "other": "Other"}
SCHEME_AMOUNT = {"pmsby": schemes.PMSBY["accidental_death"], "pmjjby": schemes.PMJJBY["death"],
                 "irctc_travel": schemes.IRCTC_TRAVEL["death"]}


class LLMUnavailable(RuntimeError):
    pass


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def quote_is_in(quote: str, text: str) -> bool:
    q = _norm(quote)
    return len(q) >= 6 and q in _norm(text)


def _amount_is_in(amount: int, text: str) -> bool:
    digits = re.sub(r"\D", "", text)
    return str(amount) in digits


def _to_cover(item: dict, source: str, ref: str, text: str) -> Cover:
    t = item["type"] if item["type"] in TYPES else "other"
    stated = item.get("sum_insured_inr")
    amount = SCHEME_AMOUNT.get(t) or (int(stated) if stated and _amount_is_in(int(stated), text) else None)
    key = hashlib.sha1(item["evidence_quote"].encode()).hexdigest()[:6]
    rule_type = t if t in {"pmsby", "pmjjby", "loan_protection"} else "other"
    return Cover(
        id=f"{t}:llm-{key}", type=rule_type, name=item["name"][:80], kind=KIND[t], sum_insured=amount,
        payee="lender" if t == "loan_protection" else "nominee",
        attrs={"what_it_pays": item.get("what_it_pays", ""), "conditions": item.get("conditions", []), "llm_type": t},
        evidence=[Evidence(source, ref, item["evidence_quote"][:300])], found_by="llm", confidence=item.get("confidence", "medium"),
    )


def _api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY")
    env = Path(".env")
    if not key and env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "GEMINI_API_KEY":
                key = value.strip().strip("\"'")
    if not key:
        raise LLMUnavailable("No Gemini key: set GEMINI_API_KEY or put it in a .env file")
    return key


def _post(body: dict, attempts: int = 3) -> dict:
    req = urllib.request.Request(URL.format(model=MODEL), data=json.dumps(body).encode(),
                                 headers={"x-goog-api-key": _api_key(), "Content-Type": "application/json"})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 503) and attempt < attempts - 1:
                time.sleep(2 ** (attempt + 1))  # busy model: wait 2 s, then 4 s
                continue
            try:
                message = json.loads(e.read())["error"]["message"]
            except (ValueError, KeyError, TypeError):
                message = e.reason
            raise LLMUnavailable(f"Gemini request failed: HTTP {e.code}: {message}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise LLMUnavailable(f"Gemini unreachable: {getattr(e, 'reason', e)}") from e


def extract(text: str, source: str = "text", ref: str = "text:1", post=None) -> list[Cover]:
    """Ask Gemini for covers in `text`. Raises LLMUnavailable when Gemini cannot be reached."""
    text = text.strip()
    if not text:
        return []
    if len(text) > MAX_CHARS:
        raise ValueError(f"Text is {len(text):,} characters; split it into parts under {MAX_CHARS:,} before extraction.")
    data = (post or _post)({
        "systemInstruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": f"Source: {source}\n\n<text>\n{text}\n</text>"}]}],
        "generationConfig": {"responseMimeType": "application/json", "responseJsonSchema": SCHEMA,
                             "thinkingConfig": {"thinkingLevel": "low"}},
    })

    candidates = data.get("candidates") or []
    if not candidates or candidates[0].get("finishReason") not in (None, "STOP"):
        return []  # blocked, cut off or empty: report nothing rather than guess
    raw = "".join(p.get("text", "") for p in candidates[0].get("content", {}).get("parts", []) if not p.get("thought"))
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [_to_cover(item, source, ref, text) for item in data.get("covers", []) if quote_is_in(item.get("evidence_quote", ""), text)]
