"""Adapter parsers against recorded upstream payloads (no network)."""

from collections import Counter

import pytest

from gpu_index.catalog import GPUS
from gpu_index.models import Observation
from gpu_index.sources import ADAPTERS, Stamp
from tests.conftest import STAMP, load_fixture


def parse(source_id: str) -> list[Observation]:
    return ADAPTERS[source_id].parse(load_fixture(source_id), STAMP)


@pytest.mark.parametrize("source_id", sorted(ADAPTERS))
def test_fixture_meets_minimum_volume_and_schema(source_id: str) -> None:
    rows = parse(source_id)
    assert len(rows) >= ADAPTERS[source_id].min_rows
    for o in rows:
        assert o.source == source_id
        assert o.gpu_model in GPUS
        assert o.gpu_count >= 1
        assert o.usd_per_gpu_hour == pytest.approx(o.usd_per_hour / o.gpu_count, abs=1e-3)
        assert o.date == STAMP.date


def find(rows: list[Observation], **attrs: object) -> Observation:
    matches = [o for o in rows if all(getattr(o, k) == v for k, v in attrs.items())]
    assert len(matches) == 1, f"expected one match for {attrs}, got {len(matches)}"
    return matches[0]


def test_azure_normalizes_eight_gpu_vm_to_per_gpu_price() -> None:
    o = find(parse("azure"), sku="Standard_ND96isr_H100_v5", region="eastus", pricing="on_demand")
    assert (o.gpu_model, o.gpu_count, o.usd_per_hour) == ("H100", 8, 98.32)
    assert o.usd_per_gpu_hour == pytest.approx(12.29)
    assert o.segment == "hyperscaler" and o.geo == "NA"


def test_azure_excludes_windows_low_priority_sovereign_and_undiscounted_spot() -> None:
    rows = parse("azure")
    assert not any(o.region.startswith("usgov") for o in rows)
    on_demand = {(o.sku, o.region): o.usd_per_hour for o in rows if o.pricing == "on_demand"}
    for o in rows:
        if o.pricing == "spot" and (o.sku, o.region) in on_demand:
            assert o.usd_per_hour < on_demand[(o.sku, o.region)]
    # Windows meters are priced higher than Linux; none should survive for this SKU/region.
    assert find(rows, sku="Standard_ND96isr_H100_v5", region="westus3", pricing="on_demand")


def test_aws_maps_instance_types() -> None:
    o = find(parse("aws"), sku="p5.48xlarge", region="us-east-1")
    assert (o.gpu_model, o.gpu_count) == ("H100", 8)
    assert o.usd_per_gpu_hour == pytest.approx(55.04 / 8, abs=1e-3)


def test_lambda_reads_every_instance_tab() -> None:
    rows = parse("lambda")
    h100 = [o for o in rows if o.gpu_model == "H100"]
    assert sorted(o.gpu_count for o in h100) == [1, 2, 4, 8]
    assert find(rows, gpu_model="H100", gpu_count=8).usd_per_gpu_hour == pytest.approx(3.99)
    assert all(o.segment == "neocloud" for o in rows)


def test_runpod_splits_secure_and_community_clouds() -> None:
    rows = [o for o in parse("runpod") if o.gpu_model == "H100"]
    assert Counter(o.segment for o in rows) == {"neocloud": 1, "marketplace": 1}


def test_vast_summarizes_offers_to_one_median_per_model() -> None:
    rows = parse("vast")
    assert len({o.gpu_model for o in rows}) == len(rows)
    assert all(o.sample_size >= 1 and o.sku == "median-offer" for o in rows)
    assert sum(o.sample_size for o in rows) > len(rows)


def test_vast_splits_a100_by_memory() -> None:
    offers = [
        {"gpu_name": "A100 SXM4", "gpu_ram": 40960, "num_gpus": 1, "dph_total": 0.8},
        {"gpu_name": "A100 SXM4", "gpu_ram": 81920, "num_gpus": 2, "dph_total": 3.0},
    ] * 5
    rows = ADAPTERS["vast"].parse(offers, STAMP)
    assert {o.gpu_model: o.usd_per_gpu_hour for o in rows} == {"A100-40GB": 0.8, "A100-80GB": 1.5}


def test_vast_skips_models_with_too_few_listings() -> None:
    from gpu_index.sources.vast import MIN_OFFERS

    def offers(name: str, n: int) -> list[dict[str, object]]:
        return [{"gpu_name": name, "gpu_ram": 81920, "num_gpus": 1, "dph_total": 2.0}] * n

    rows = ADAPTERS["vast"].parse(
        offers("B200", MIN_OFFERS - 1) + offers("H200", MIN_OFFERS), STAMP
    )
    assert [(o.gpu_model, o.sample_size) for o in rows] == [("H200", MIN_OFFERS)]


def test_coreweave_normalizes_instances_and_dedupes_repeated_listings() -> None:
    rows = parse("coreweave")
    h100 = find(rows, gpu_model="H100", pricing="on_demand")
    assert (h100.gpu_count, h100.usd_per_hour) == (8, 49.24)
    assert h100.usd_per_gpu_hour == pytest.approx(6.155)
    assert find(rows, gpu_model="H100", pricing="spot").usd_per_gpu_hour < h100.usd_per_gpu_hour
    assert all(o.segment == "neocloud" for o in rows)


def test_nebius_switches_to_announced_prices_on_their_effective_date() -> None:
    from gpu_index.sources import nebius

    html = load_fixture("nebius")
    before = nebius.parse(html, Stamp("2026-09-15", "2026-09-15T06:00:00+00:00"))
    after = nebius.parse(html, Stamp("2026-10-04", "2026-10-04T06:00:00+00:00"))
    assert find(before, gpu_model="H100").usd_per_gpu_hour == 3.85
    assert find(after, gpu_model="H100").usd_per_gpu_hour == 4.50
    assert not any(o.gpu_model == "L40S" for o in after)  # "from $X" rows skipped


def test_nebius_price_column_logic() -> None:
    from datetime import date

    from gpu_index.sources.nebius import price_column

    headers = ["Item", "vCPUs", "On-demand, GPU-hour", "GPU-hour (Effective October 1, 2026)"]
    assert price_column(headers, date(2026, 9, 30)) == 2
    assert price_column(headers, date(2026, 10, 1)) == 3
    assert price_column(["Item", "Price"], date(2026, 10, 1)) is None


def test_crusoe_skips_inference_endpoints_and_splits_a100_form_factors() -> None:
    rows = parse("crusoe")
    assert len([o for o in rows if o.gpu_model == "H100"]) == 1  # not the $5.50 endpoint
    assert find(rows, gpu_model="A100-80GB").usd_per_gpu_hour == 2.30
    assert find(rows, gpu_model="A100-80GB-PCIe").usd_per_gpu_hour == 2.00


def test_hyperstack_maps_pcie_cards_explicitly_and_ignores_reservations() -> None:
    rows = parse("hyperstack")
    assert find(rows, sku="NVIDIA H100", pricing="on_demand").gpu_model == "H100-PCIe"
    assert find(rows, sku="NVIDIA H100 SXM", pricing="on_demand").usd_per_gpu_hour == 3.20
    assert {o.pricing for o in rows} == {"on_demand", "spot"}
    assert not any(o.usd_per_gpu_hour == 2.72 for o in rows)  # reservation price
