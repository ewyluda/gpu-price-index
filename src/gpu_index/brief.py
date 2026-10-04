"""Daily market brief: a deterministic template, optionally rewritten by Claude.

The LLM path is guarded by a numeric fact-check: every dollar figure, percentage
and multiple in the model's output must match a number derived from the day's
facts. If the draft fails twice, the brief falls back to the template, so a
hallucinated price can never reach the dashboard.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

MODEL = "claude-opus-5-5"
HEADLINE_GPUS = ("B200", "H200", "H100", "MI300X", "A100-80GB", "L40S")

SYSTEM_PROMPT = """\
You write a short daily market brief on GPU rental prices for people who plan and \
buy AI compute capacity: data-center build-out teams, capacity planners, and \
infrastructure finance.

You are given FACTS as JSON. Every number you write must appear in FACTS for the GPU \
you attribute it to, written exactly as shown there: dollar amounts with "$", and \
percentages with their explicit + or - sign (e.g. "+217%"). Write numbers as digits. \
Do not compute new figures, do not estimate, and do not mention anything FACTS does \
not support. When history \
is short (days_of_history below 7), describe the cross-section between segments and \
providers rather than trends.

Definitions: the market index is the median of provider medians across all \
segments. Hyperscaler premium is how much more the hyperscaler segment costs than \
the neocloud segment. Prices are on-demand list prices per GPU-hour in USD."""

BRIEF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "headline": {"type": "string", "description": "One sentence, under 20 words."},
        "bullets": {
            "type": "array",
            "items": {"type": "string"},
            "description": "3 to 5 findings, one sentence each.",
        },
        "watch": {"type": "string", "description": "One thing to watch next."},
    },
    "required": ["headline", "bullets", "watch"],
    "additionalProperties": False,
}


def _money(value: float) -> str:
    return f"${value:,.2f}"


def _pct(value: float) -> str:
    return f"{value * 100:+.0f}%"


def facts(snap: dict[str, Any]) -> dict[str, Any]:
    """The compact, pre-rounded fact sheet both brief generators work from."""
    gpus = []
    for g in snap["gpus"]:
        if g["key"] not in HEADLINE_GPUS:
            continue
        s = g["series"]
        cheapest = g["providers"][0] if g["providers"] else None
        gpus.append(
            {
                "gpu": g["name"],
                "market_index": _money(s["index"]["value"]),
                "providers": s["index"]["n_providers"],
                **{
                    f"{seg}_median": _money(s[seg]["value"])
                    for seg in ("hyperscaler", "neocloud", "marketplace")
                    if seg in s
                },
                "hyperscaler_premium": (
                    _pct(g["hyperscaler_premium"]) if g["hyperscaler_premium"] is not None else None
                ),
                "change_7d": (
                    _pct(s["index"]["change_7d"]) if s["index"]["change_7d"] is not None else None
                ),
                "cheapest_provider": cheapest["provider"] if cheapest else None,
                "cheapest_provider_median": _money(cheapest["median"]) if cheapest else None,
                "usd_per_pflop_hour": _money(g["usd_per_pflop_hour"]),
            }
        )
    best_value = min(gpus, key=lambda g: float(g["usd_per_pflop_hour"].strip("$")), default=None)
    return {
        "as_of": snap["as_of"],
        "days_of_history": snap["days_of_history"],
        "trend_window_days": 7,
        "provider_count": len(snap["providers"]),
        "best_price_performance": best_value["gpu"] if best_value else None,
        "gpus": gpus,
    }


def template_brief(f: dict[str, Any]) -> dict[str, Any]:
    by_name = {g["gpu"]: g for g in f["gpus"]}
    h100 = by_name.get("H100 SXM")
    bullets = []
    for g in f["gpus"][:4]:
        line = (
            f"{g['gpu']}: market index {g['market_index']}/GPU-hr across {g['providers']} providers"
        )
        if g.get("hyperscaler_premium"):
            line += f"; hyperscaler premium {g['hyperscaler_premium']} over neoclouds"
        bullets.append(line + ".")
    best = f["best_price_performance"]
    if best:
        bullets.append(
            f"Best price-performance: {best} at "
            f"{by_name[best]['usd_per_pflop_hour']} per dense BF16 PFLOP-hour."
        )
    headline = (
        f"H100 rents for {h100['market_index']}/GPU-hr at the market median"
        if h100
        else f"GPU rental prices as of {f['as_of']}"
    )
    watch = (
        f"Trend signals begin once {f['trend_window_days']} days of history have accumulated."
        if f["days_of_history"] < f["trend_window_days"]
        else "Watch whether the hyperscaler premium narrows as Blackwell capacity grows."
    )
    return {"headline": headline, "bullets": bullets, "watch": watch}


# --- fact-checking -----------------------------------------------------------
#
# Every number in a draft is extracted and must match a value in the fact sheet for
# the GPU its sentence names (or, if the sentence names none or several, any GPU it
# could refer to). Percentages must carry the sign given in the facts, so "fell 12%"
# can't be written for "+12%". Model names ("H100", "MI300X"), memory sizes ("80GB")
# and ISO dates are stripped first so their digits aren't mistaken for claims.

_NOT_CLAIMS = re.compile(r"\b(?:[A-Z]{1,3}\d{2,4}[A-Z]*|BF16|FP\d+|\d+\s?GB)\b|\d{4}-\d{2}-\d{2}")
_NUMBER = re.compile(
    r"(?P<usd>\$\s?|\bUSD\s?)?(?P<sign>[+\-\u2212])?(?P<num>\d[\d,]*(?:\.\d+)?)"
    r"(?P<unit>\s?(?:%|percent\b|x\b|\u00d7|dollars\b))?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Claim:
    kind: str  # "usd" | "pct" | "multiple" | "num"
    value: float
    text: str


def extract_claims(text: str) -> list[Claim]:
    claims = []
    for m in _NUMBER.finditer(_NOT_CLAIMS.sub(" ", text)):
        value = float(m.group("num").replace(",", ""))
        unit = (m.group("unit") or "").strip().lower()
        if m.group("usd") or unit == "dollars":
            kind = "usd"
        elif unit in {"%", "percent"}:
            kind = "pct"
            if m.group("sign") in {"-", "\u2212"}:
                value = -value
            elif not m.group("sign"):
                value = float("nan")  # unsigned percentages are never accepted
        elif unit in {"x", "\u00d7"}:
            kind = "multiple"
        else:
            kind = "num"
        claims.append(Claim(kind, value, m.group(0).strip()))
    return claims


Allowed = dict[str, set[float]]


def _allowed_from(values: Any) -> Allowed:
    allowed: Allowed = {"usd": set(), "pct": set(), "multiple": set(), "num": set()}
    for claim in extract_claims(json.dumps(values)):
        allowed[claim.kind].add(claim.value)
        if claim.kind == "pct":  # "+95%" may be phrased as "1.95x" or "2x"
            for digits in (2, 1, 0):
                allowed["multiple"].add(round(1 + claim.value / 100, digits))
    allowed["num"] |= allowed["usd"]  # "3.82 per GPU-hour" without the "$"
    return allowed


def _merge(*sets: Allowed) -> Allowed:
    return {k: set().union(*(s[k] for s in sets)) for k in ("usd", "pct", "multiple", "num")}


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.;!?])\s+", text) if s.strip()]


def unsupported_claims(text: str, f: dict[str, Any]) -> list[str]:
    shared = {k: v for k, v in f.items() if k != "gpus"}
    shared["as_of_parts"] = [int(p) for p in f["as_of"].split("-")]
    global_allowed = _allowed_from(shared)
    per_gpu = {g["gpu"]: _allowed_from(g) for g in f["gpus"]}
    aliases = {g["gpu"].split()[0]: g["gpu"] for g in f["gpus"]}

    bad = []
    for sentence in _sentences(text):
        named = {gpu for alias, gpu in aliases.items() if re.search(rf"\b{alias}\b", sentence)}
        scope = _merge(global_allowed, *(per_gpu[g] for g in (named or per_gpu)))
        for claim in extract_claims(sentence):
            if not any(abs(claim.value - a) < 1e-6 for a in scope[claim.kind]):
                bad.append(claim.text)
    return bad


# --- generation ----------------------------------------------------------------


# USD per million tokens (input, output), from Anthropic's published pricing.
# A server-side fallback can serve a request on another model, so cost is priced by
# the model that actually answered (response.model), not the one requested.
PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-5-5": (2.0, 10.0),
}


@dataclass
class Usage:
    """Tokens and cost across every request made for one brief, retries included."""

    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    usd: float | None = 0.0
    models: list[str] = field(default_factory=list)

    def add(self, model: str, input_tokens: int, output_tokens: int) -> None:
        self.requests += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        if model not in self.models:
            self.models.append(model)
        price = PRICES_PER_MTOK.get(model)
        if price is None or self.usd is None:
            self.usd = None  # unknown model: report tokens, don't guess dollars
        else:
            self.usd += (input_tokens * price[0] + output_tokens * price[1]) / 1_000_000

    def to_dict(self) -> dict[str, Any]:
        return {
            "requests": self.requests,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "usd": None if self.usd is None else round(self.usd, 4),
            "models": self.models,
        }


def _draft(client: Any, f: dict[str, Any], feedback: str | None, usage: Usage) -> dict[str, Any]:
    content = f"FACTS:\n{json.dumps(f, indent=1)}"
    if feedback:
        content += f"\n\nYour previous draft used figures not in FACTS: {feedback}. Rewrite it."
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
        output_config={
            "effort": "medium",
            "format": {"type": "json_schema", "schema": BRIEF_SCHEMA},
        },
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    usage.add(
        getattr(response, "model", None) or MODEL,
        response.usage.input_tokens,
        response.usage.output_tokens,  # includes thinking tokens, which are billed as output
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("model declined to write the brief")
    text = next(b.text for b in response.content if b.type == "text")
    draft: dict[str, Any] = json.loads(text)
    return draft


def llm_brief(
    f: dict[str, Any], client: Any, usage: Usage, attempts: int = 2
) -> dict[str, Any] | None:
    feedback = None
    for _ in range(attempts):
        draft = _draft(client, f, feedback, usage)
        text = " ".join([draft["headline"], *draft["bullets"], draft["watch"]])
        bad = unsupported_claims(text, f)
        if not bad:
            return draft
        log.warning("brief draft rejected, unsupported figures: %s", bad)
        feedback = ", ".join(bad)
    return None


def generate(
    snap: dict[str, Any], use_llm: bool | None = None, client: Any = None
) -> dict[str, Any]:
    """Return the brief document written to site/data/brief.json."""
    f = facts(snap)
    if use_llm is None:
        use_llm = bool(os.environ.get("ANTHROPIC_API_KEY"))
    result: dict[str, Any] = {"as_of": snap["as_of"], "generator": "template", "model": None}
    if use_llm:
        usage = Usage()
        try:
            if client is None:
                import anthropic

                client = anthropic.Anthropic()
            draft = llm_brief(f, client, usage)
        except Exception as exc:  # the brief is optional; the index is not
            log.warning("LLM brief failed, using template: %s", exc)
            draft = None
            result["fallback_reason"] = f"{type(exc).__name__}: {exc}"
        result["usage"] = usage.to_dict()  # spent even when the draft is rejected
        if draft is not None:
            model = usage.models[-1] if usage.models else MODEL
            return {**result, **draft, "generator": "claude", "model": model, "fact_checked": True}
        result.setdefault("fallback_reason", "draft failed numeric fact-check twice")
    return {**result, **template_brief(f)}
