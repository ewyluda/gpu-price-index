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


def test_extract_claims_finds_dollars_percents_and_multiples() -> None:
    claims = brief.extract_claims("H100 at $3.81/GPU-hr, up +12% and 2.9x the A100; 8 GPUs")
    assert [(c.kind, c.value) for c in claims] == [("usd", 3.81), ("pct", 12.0), ("multiple", 2.9)]


def test_template_brief_passes_its_own_fact_check(snap: dict[str, Any]) -> None:
    f = brief.facts(snap)
    doc = brief.template_brief(f)
    text = " ".join([doc["headline"], *doc["bullets"], doc["watch"]])
    assert brief.unsupported_claims(text, f) == []
    assert 3 <= len(doc["bullets"]) <= 5


def test_fact_check_rejects_invented_figures(snap: dict[str, Any]) -> None:
    f = brief.facts(snap)
    h100 = next(g for g in f["gpus"] if g["gpu"] == "H100 SXM")
    real = f"H100 rents for {h100['market_index']}/GPU-hr."
    assert brief.unsupported_claims(real, f) == []
    assert brief.unsupported_claims("H100 fell 37% to $1.23/GPU-hr.", f) == ["37%", "$1.23"]


class FakeClient:
    """Stands in for anthropic.Anthropic; returns queued JSON drafts."""

    def __init__(self, drafts: list[dict[str, Any]]) -> None:
        self.drafts = drafts
        self.calls: list[dict[str, Any]] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        block = SimpleNamespace(type="text", text=json.dumps(self.drafts.pop(0)))
        return SimpleNamespace(stop_reason="end_turn", content=[block])


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
