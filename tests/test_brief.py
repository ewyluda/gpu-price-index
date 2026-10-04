import json
from types import SimpleNamespace
from typing import Any

import pytest

from gpu_index import brief
from gpu_index.index import snapshot
from gpu_index.models import Observation


@pytest.fixture
def snap(fixture_rows: list[Observation]) -> dict[str, Any]:
    return snapshot(fixture_rows)


def test_extract_claims_classifies_units_and_keeps_signs() -> None:
    claims = brief.extract_claims(
        "H100 80GB at $3.82/GPU-hr, down -12% and 2.9X the A100; 250 percent; 9.99 per hour"
    )
    kinds = [(c.kind, c.value) for c in claims[:3]]
    assert kinds == [("usd", 3.82), ("pct", -12.0), ("multiple", 2.9)]
    assert claims[3].kind == "pct" and claims[3].value != claims[3].value  # unsigned -> NaN
    assert (claims[4].kind, claims[4].value) == ("num", 9.99)
    assert all("100" not in c.text and "80" not in c.text for c in claims)  # model names skipped


def test_template_brief_passes_its_own_fact_check(snap: dict[str, Any]) -> None:
    f = brief.facts(snap)
    doc = brief.template_brief(f)
    text = " ".join([doc["headline"], *doc["bullets"], doc["watch"]])
    assert brief.unsupported_claims(text, f) == []
    assert 3 <= len(doc["bullets"]) <= 5


def test_fact_check_rejects_invented_figures(snap: dict[str, Any]) -> None:
    f = brief.facts(snap)
    h100 = next(g for g in f["gpus"] if g["gpu"] == "H100 SXM")
    premium = h100["hyperscaler_premium"]
    ok = f"H100 rents for {h100['market_index']}/GPU-hr; hyperscalers run {premium} over neoclouds."
    assert brief.unsupported_claims(ok, f) == []
    assert brief.unsupported_claims("H100 fell 37% to $1.23/GPU-hr.", f) == ["37%", "$1.23"]


@pytest.mark.parametrize(
    "template",
    [
        "H100 prices run {flipped} versus neoclouds.",  # sign flipped
        "H100 premium is {unsigned} over neoclouds.",  # sign dropped
        "H100 rents for 9.99 per GPU-hour.",  # bare decimal
        "H100 costs 9.99 dollars.",  # spelled-out unit
        "H100 is 7X the price.",  # uppercase multiple
        "H100 is listed by 12 providers.",  # invented count
        "A100 rents for {h100_hyper}.",  # real number, wrong GPU
    ],
)
def test_fact_check_catches_evasions(snap: dict[str, Any], template: str) -> None:
    f = brief.facts(snap)
    h100 = next(g for g in f["gpus"] if g["gpu"] == "H100 SXM")
    premium = h100["hyperscaler_premium"]
    text = template.format(
        flipped="-" + premium.lstrip("+"),
        unsigned=premium.lstrip("+"),
        h100_hyper=h100["hyperscaler_median"],
    )
    assert brief.unsupported_claims(text, f), text


def test_facts_survive_a_snapshot_without_headline_gpus(snap: dict[str, Any]) -> None:
    f = brief.facts({**snap, "gpus": []})
    assert f["best_price_performance"] is None
    assert brief.template_brief(f)["headline"].startswith("GPU rental prices as of")


class FakeClient:
    """Stands in for anthropic.Anthropic; returns queued JSON drafts."""

    def __init__(self, drafts: list[dict[str, Any]], model: str = brief.MODEL) -> None:
        self.drafts = drafts
        self.model = model
        self.calls: list[dict[str, Any]] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        block = SimpleNamespace(type="text", text=json.dumps(self.drafts.pop(0)))
        usage = SimpleNamespace(input_tokens=1_500, output_tokens=2_000)
        return SimpleNamespace(
            stop_reason="end_turn", content=[block], model=self.model, usage=usage
        )


def _draft(headline: str) -> dict[str, Any]:
    return {"headline": headline, "bullets": ["a", "b", "c"], "watch": "w"}


def test_llm_brief_used_when_fact_check_passes(snap: dict[str, Any]) -> None:
    idx = brief.facts(snap)["gpus"][0]["market_index"]
    client = FakeClient([_draft(f"Index at {idx}")])
    doc = brief.generate(snap, use_llm=True, client=client)
    assert doc["generator"] == "claude" and doc["fact_checked"] is True
    request = client.calls[0]
    assert request["model"] == brief.MODEL
    assert request["output_config"]["format"]["type"] == "json_schema"
    assert "FACTS" in request["messages"][0]["content"]


def test_llm_brief_retries_with_feedback_then_falls_back(snap: dict[str, Any]) -> None:
    client = FakeClient([_draft("H100 hits $99.99"), _draft("Still $88.88")])
    doc = brief.generate(snap, use_llm=True, client=client)
    assert doc["generator"] == "template"
    assert "fact-check" in doc["fallback_reason"]
    assert "$99.99" in client.calls[1]["messages"][0]["content"]


def test_llm_errors_never_break_the_pipeline(snap: dict[str, Any]) -> None:
    class Broken:
        beta = SimpleNamespace(messages=SimpleNamespace(create=lambda **_: 1 / 0))

    doc = brief.generate(snap, use_llm=True, client=Broken())
    assert doc["generator"] == "template"
    assert "ZeroDivisionError" in doc["fallback_reason"]


def test_usage_and_cost_are_recorded(snap: dict[str, Any]) -> None:
    idx = brief.facts(snap)["gpus"][0]["market_index"]
    doc = brief.generate(snap, use_llm=True, client=FakeClient([_draft(f"Index at {idx}")]))
    # 1,500 in x $4/M + 2,000 out x $20/M = $0.006 + $0.04
    assert doc["usage"] == {
        "requests": 1,
        "input_tokens": 1_500,
        "output_tokens": 2_000,
        "usd": 0.046,
        "models": [brief.MODEL],
    }


def test_rejected_drafts_are_still_billed(snap: dict[str, Any]) -> None:
    client = FakeClient([_draft("H100 hits $99.99"), _draft("Still $88.88")])
    doc = brief.generate(snap, use_llm=True, client=client)
    assert doc["generator"] == "template"
    assert doc["usage"]["requests"] == 2 and doc["usage"]["usd"] == 0.092


def test_fallback_model_is_priced_by_the_model_that_answered(snap: dict[str, Any]) -> None:
    idx = brief.facts(snap)["gpus"][0]["market_index"]
    doc = brief.generate(
        snap, use_llm=True, client=FakeClient([_draft(f"Index {idx}")], model="claude-opus-4-8")
    )
    assert doc["model"] == "claude-opus-4-8"
    assert doc["usage"]["usd"] == 0.0575  # $5 in / $25 out
    unknown = brief.generate(
        snap, use_llm=True, client=FakeClient([_draft(f"Index {idx}")], model="claude-x")
    )
    assert unknown["usage"]["usd"] is None  # never guess a price


def test_month_to_date_spend_sums_the_usage_log(tmp_path: Any) -> None:
    from gpu_index import publish

    log = tmp_path / "llm_usage.jsonl"
    for day, usd in [("2026-09-30", 0.05), ("2026-10-01", 0.04), ("2026-10-02", 0.03)]:
        doc = {"as_of": day, "generator": "claude", "usage": {"requests": 1, "usd": usd}}
        publish.record_llm_usage(doc, log)
    assert doc["usage"]["month_to_date_usd"] == 0.07  # September excluded
    assert len(log.read_text().splitlines()) == 3
