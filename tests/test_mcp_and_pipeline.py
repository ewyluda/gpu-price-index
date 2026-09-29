import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest

from gpu_index import mcp_server, pipeline, publish
from gpu_index.models import Observation
from gpu_index.sources import SourceAdapter, Stamp
from tests.conftest import make_obs


@pytest.fixture
def site_data(
    tmp_path: Path, fixture_rows: list[Observation], monkeypatch: pytest.MonkeyPatch
) -> Path:
    monkeypatch.setattr(publish, "RUNS_LOG", tmp_path / "runs.jsonl")
    publish.build(fixture_rows, out=tmp_path)
    monkeypatch.setattr(mcp_server, "SITE_DATA", tmp_path)
    monkeypatch.delenv("GPU_INDEX_DATA_URL", raising=False)
    return tmp_path


def test_publish_writes_every_artifact(site_data: Path) -> None:
    for name in [
        "latest.json",
        "history.json",
        "index-history.csv",
        "observations-latest.csv",
        "status.json",
    ]:
        assert (site_data / name).stat().st_size > 0


def test_mcp_registers_expected_tools() -> None:
    tools = {t.name for t in asyncio.run(mcp_server.server.list_tools())}
    assert tools == {
        "list_gpus",
        "get_prices",
        "get_history",
        "estimate_cluster_cost",
        "compare_price_performance",
        "pipeline_status",
    }


def test_mcp_tools_answer_from_published_data(site_data: Path) -> None:
    gpus = mcp_server.list_gpus()
    assert any(g["key"] == "H100" for g in gpus["gpus"])
    assert mcp_server.get_prices("h100 sxm")["key"] == "H100"  # accepts display name
    quote = mcp_server.estimate_cluster_cost("H100", 512, 24 * 90)
    assert quote["gpu_hours"] == 512 * 24 * 90 and quote["quotes"]
    ranking = mcp_server.compare_price_performance()["ranking"]
    assert ranking == sorted(ranking, key=lambda r: r["usd_per_pflop_hour"])
    with pytest.raises(ValueError, match="unknown GPU"):
        mcp_server.get_prices("TPU v5p")


def _adapter(id: str, parse: Any) -> SourceAdapter:
    return SourceAdapter(
        id=id, name=id, homepage="", terms="", min_rows=1, fetch=lambda _client: None, parse=parse
    )


def test_one_failing_source_does_not_block_the_others(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(_payload: Any, _stamp: Stamp) -> list[Observation]:
        raise httpx.ConnectError("upstream down")

    monkeypatch.setenv("GPU_INDEX_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        pipeline,
        "ADAPTERS",
        {
            "good": _adapter("good", lambda _p, s: [make_obs(date=s.date, source="good")]),
            "bad": _adapter("bad", boom),
        },
    )
    run = pipeline.collect(stamp=Stamp("2026-09-28", "2026-09-28T06:17:00+00:00"))
    assert not run.ok
    status = {s.id: s for s in run.sources}
    assert status["good"].ok and status["good"].rows == 1
    assert not status["bad"].ok and "ConnectError" in (status["bad"].error or "")
    assert (tmp_path / "2026" / "2026-09-28.csv").exists()
