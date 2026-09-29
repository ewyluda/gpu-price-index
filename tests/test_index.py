import pytest

from gpu_index.index import daily_values, estimate_cost, pct_change, snapshot
from gpu_index.models import Observation
from tests.conftest import make_obs


def test_provider_with_many_regions_does_not_outvote_others() -> None:
    # One hyperscaler with 50 regional rows at $12, two neoclouds at $2 and $3.
    rows = [
        make_obs(
            source="az",
            provider="Azure",
            segment="hyperscaler",
            region=f"r{i}",
            usd_per_gpu_hour=12.0,
        )
        for i in range(50)
    ]
    rows += [
        make_obs(provider="Neo A", usd_per_gpu_hour=2.0),
        make_obs(provider="Neo B", usd_per_gpu_hour=3.0),
    ]
    values = daily_values(rows)["H100"]
    assert values["index"] == (3.0, 3)  # median of [12, 2, 3], one vote per provider
    assert values["hyperscaler"] == (12.0, 1)
    assert values["neocloud"] == (2.5, 2)


def test_spot_is_tracked_separately_from_on_demand() -> None:
    rows = [
        make_obs(provider="Azure", segment="hyperscaler", usd_per_gpu_hour=12.0),
        make_obs(
            provider="Azure", segment="hyperscaler", pricing="spot", sku="s", usd_per_gpu_hour=3.0
        ),
    ]
    values = daily_values(rows)["H100"]
    assert values["index"] == (12.0, 1)
    assert values["spot"] == (3.0, 1)


def test_pct_change_uses_last_value_on_or_before_the_window() -> None:
    dates = ["2026-09-01", "2026-09-05", "2026-09-08", "2026-09-12"]
    assert pct_change(dates, [2.0, 2.5, None, 3.0], 7) == pytest.approx(0.2)  # vs 09-05
    assert pct_change(dates, [2.0, 2.5, None, 3.0], 30) is None  # not enough history
    assert pct_change(dates, [2.0, 2.5, 2.8, None], 7) is None


def _two_days() -> list[Observation]:
    return [
        make_obs(date="2026-09-01", provider="Neo", usd_per_gpu_hour=2.0),
        make_obs(date="2026-09-08", provider="Neo", usd_per_gpu_hour=2.2),
        make_obs(
            date="2026-09-08",
            provider="Hyper",
            segment="hyperscaler",
            usd_per_gpu_hour=6.6,
            geo="NA",
            region="eastus",
        ),
    ]


def test_snapshot_derives_premium_changes_and_price_performance() -> None:
    snap = snapshot(_two_days())
    assert snap["as_of"] == "2026-09-08" and snap["days_of_history"] == 2
    (h100,) = snap["gpus"]
    assert h100["series"]["neocloud"]["change_7d"] == pytest.approx(0.1)
    assert h100["hyperscaler_premium"] == pytest.approx(2.0)  # 6.6 / 2.2 - 1
    assert h100["series"]["index"]["value"] == pytest.approx(4.4)
    assert h100["usd_per_pflop_hour"] == pytest.approx(4.4 / 0.989, abs=0.005)  # cents
    assert h100["regional"] == {"NA": {"hyperscaler": 6.6}}
    assert [p["provider"] for p in h100["providers"]] == ["Neo", "Hyper"]


def test_estimate_cost_quotes_cheapest_first_and_filters_segment() -> None:
    snap = snapshot(_two_days())
    quote = estimate_cost(snap, "H100", gpu_count=512, hours=24 * 30)
    assert quote["gpu_hours"] == 512 * 720
    assert [q["provider"] for q in quote["quotes"]] == ["Neo", "Hyper"]
    assert quote["quotes"][0]["total_usd"] == pytest.approx(2.2 * 512 * 720)
    only_hyper = estimate_cost(snap, "H100", 8, 1, segment="hyperscaler")
    assert [q["provider"] for q in only_hyper["quotes"]] == ["Hyper"]
    with pytest.raises(KeyError):
        estimate_cost(snap, "B200", 1, 1)


def test_snapshot_on_real_fixtures_covers_headline_gpus(fixture_rows: list[Observation]) -> None:
    snap = snapshot(fixture_rows)
    keys = {g["key"] for g in snap["gpus"]}
    assert {"H100", "H200", "B200", "A100-80GB", "MI300X", "L40S"} <= keys
    h100 = next(g for g in snap["gpus"] if g["key"] == "H100")
    assert h100["series"]["index"]["n_providers"] >= 5
    assert h100["hyperscaler_premium"] > 0
