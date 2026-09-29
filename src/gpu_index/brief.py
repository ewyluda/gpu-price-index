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
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

MODEL = "claude-opus-5-5"
HEADLINE_GPUS = ("B200", "H200", "H100", "MI300X", "A100-80GB", "L40S")

SYSTEM_PROMPT = """\
You write a short daily market brief on GPU rental prices for people who plan and \
buy AI compute capacity: data-center build-out teams, capacity planners, and \
infrastructure finance.

You are given FACTS as JSON. Every dollar amount, percentage and multiple you write \
must come directly from FACTS, rounded as shown there. Do not compute new figures, \
do not estimate, and do not mention anything FACTS does not support. When history \
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
    best_value = min(gpus, key=lambda g: float(g["usd_per_pflop_hour"].strip("$")))
    return {
        "as_of": snap["as_of"],
        "days_of_history": snap["days_of_history"],
        "provider_count": len(snap["providers"]),
        "best_price_performance": best_value["gpu"],
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
            premium = g["hyperscaler_premium"].lstrip("+")
            direction = "above" if not premium.startswith("-") else "below"
            line += f"; hyperscaler list prices run {premium.lstrip('-')} {direction} neoclouds"
        bullets.append(line + ".")
    bullets.append(
        f"Best price-performance: {f['best_price_performance']} at "
        f"{by_name[f['best_price_performance']]['usd_per_pflop_hour']} per dense BF16 PFLOP-hour."
    )
    headline = (
        f"H100 rents for {h100['market_index']}/GPU-hr at the market median"
        if h100
        else f"GPU rental prices as of {f['as_of']}"
    )
    watch = (
        "Trend signals begin once 7 days of history have accumulated."
        if f["days_of_history"] < 7
        else "Watch whether the hyperscaler premium narrows as Blackwell capacity grows."
    )
    return {"headline": headline, "bullets": bullets, "watch": watch}


# --- fact-checking -----------------------------------------------------------

_NUMBER_CLAIM = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)|([+-]?\d+(?:\.\d+)?)\s?(%|x\b|\u00d7)")


@dataclass(frozen=True)
class Claim:
    kind: str  # "usd" | "pct" | "multiple"
    value: float
    text: str


def extract_claims(text: str) -> list[Claim]:
    claims = []
    for m in _NUMBER_CLAIM.finditer(text):
        if m.group(1):
            claims.append(Claim("usd", float(m.group(1).replace(",", "")), m.group(0)))
        else:
            kind = "pct" if m.group(3) == "%" else "multiple"
            claims.append(Claim(kind, abs(float(m.group(2))), m.group(0)))
    return claims


def allowed_values(f: dict[str, Any]) -> dict[str, set[float]]:
    allowed: dict[str, set[float]] = {"usd": set(), "pct": set(), "multiple": set()}
    for claim in extract_claims(json.dumps(f)):
        allowed[claim.kind].add(claim.value)
        if claim.kind == "pct":  # "+95%" premium may be phrased as "1.95x" or "2x"
            allowed["multiple"].add(round(1 + claim.value / 100, 2))
            allowed["multiple"].add(round(1 + claim.value / 100, 1))
            allowed["multiple"].add(float(round(1 + claim.value / 100)))
    return allowed


def unsupported_claims(text: str, f: dict[str, Any]) -> list[str]:
    allowed = allowed_values(f)
    tolerance = {"usd": 0.011, "pct": 0.51, "multiple": 0.051}
    return [
        c.text
        for c in extract_claims(text)
        if not any(abs(c.value - a) <= tolerance[c.kind] for a in allowed[c.kind])
    ]


# --- generation ----------------------------------------------------------------


def _draft(client: Any, f: dict[str, Any], feedback: str | None) -> dict[str, Any]:
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
    if response.stop_reason == "refusal":
        raise RuntimeError("model declined to write the brief")
    text = next(b.text for b in response.content if b.type == "text")
    draft: dict[str, Any] = json.loads(text)
    return draft


def llm_brief(f: dict[str, Any], client: Any, attempts: int = 2) -> dict[str, Any] | None:
    feedback = None
    for _ in range(attempts):
        draft = _draft(client, f, feedback)
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
        try:
            if client is None:
                import anthropic

                client = anthropic.Anthropic()
            draft = llm_brief(f, client)
        except Exception as exc:  # the brief is optional; the index is not
            log.warning("LLM brief failed, using template: %s", exc)
            draft = None
            result["fallback_reason"] = f"{type(exc).__name__}: {exc}"
        if draft is not None:
            return {**result, **draft, "generator": "claude", "model": MODEL, "fact_checked": True}
        result.setdefault("fallback_reason", "draft failed numeric fact-check twice")
    return {**result, **template_brief(f)}
