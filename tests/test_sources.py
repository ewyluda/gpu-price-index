"""Adapter parsers against recorded upstream payloads (no network)."""

from collections import Counter

import pytest

from gpu_index.catalog import GPUS
from gpu_index.models import Observation
from gpu_index.sources import ADAPTERS
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


def _meter(price: float, start: str | None, spot: bool = False) -> dict[str, object]:
    """One ND96isr H100 v5 / eastus meter; STAMP is 2026-09-28."""
    return {
        "armSkuName": "Standard_ND96isr_H100_v5",
        "armRegionName": "eastus",
        "retailPrice": price,
        "unitOfMeasure": "1 Hour",
        "meterName": "ND96isr H100 v5 Spot" if spot else "ND96isr H100 v5",
        "productName": "Virtual Machines NDsrH100v5 Series",
        "type": "Consumption",
        "effectiveStartDate": start,
    }


def test_azure_keeps_newest_meter_when_a_price_rollover_lists_both() -> None:
    # On the 1st of the month Azure briefly serves the outgoing and incoming meter
    # for the same SKU/region; the stale one is listed last here on purpose.
    items = [
        _meter(98.32, "2026-09-01T00:00:00Z"),
        _meter(90.00, "2026-01-01T00:00:00Z"),
        _meter(30.00, "2026-09-01T00:00:00Z", spot=True),
        _meter(95.00, "2026-08-01T00:00:00Z", spot=True),
    ]
    rows = ADAPTERS["azure"].parse(items, STAMP)
    assert find(rows, pricing="on_demand").usd_per_hour == 98.32
    assert find(rows, pricing="spot").usd_per_hour == 30.00


def test_azure_ignores_meters_not_yet_in_effect() -> None:
    items = [_meter(98.32, "2026-09-01T00:00:00Z"), _meter(80.00, "2026-10-01T00:00:00Z")]
    assert find(ADAPTERS["azure"].parse(items, STAMP), pricing="on_demand").usd_per_hour == 98.32


def test_azure_breaks_same_date_ties_independent_of_api_order() -> None:
    a, b = _meter(98.32, "2026-09-01T00:00:00Z"), _meter(97.00, "2026-09-01T00:00:00Z")
    picks = {find(ADAPTERS["azure"].parse(items, STAMP)).usd_per_hour for items in ([a, b], [b, a])}
    assert picks == {97.00}


def test_azure_treats_missing_or_null_effective_date_as_oldest() -> None:
    undated = {k: v for k, v in _meter(90.00, None).items() if k != "effectiveStartDate"}
    items = [_meter(98.32, "2026-09-01T00:00:00Z"), _meter(91.00, None), undated]
    assert find(ADAPTERS["azure"].parse(items, STAMP), pricing="on_demand").usd_per_hour == 98.32


def test_azure_screens_spot_against_the_current_on_demand_rate() -> None:
    # Spot at $95 is a real discount on today's $98.32, but not on the stale $90
    # meter; it must survive however the two on-demand meters are ordered.
    items = [
        _meter(98.32, "2026-09-01T00:00:00Z"),
        _meter(90.00, "2026-08-01T00:00:00Z"),
        _meter(95.00, "2026-09-01T00:00:00Z", spot=True),
    ]
    assert find(ADAPTERS["azure"].parse(items, STAMP), pricing="spot").usd_per_hour == 95.00


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


def test_runpod_skips_offerings_flagged_unavailable() -> None:
    # The fixture's MI300X has communityCloud=false with a placeholder communityPrice.
    rows = [o for o in parse("runpod") if o.gpu_model == "MI300X"]
    assert [o.provider for o in rows] == ["RunPod Secure Cloud"]


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


def test_nebius_reads_on_demand_column_not_preemptible() -> None:
    rows = parse("nebius")
    assert find(rows, gpu_model="H100").usd_per_gpu_hour == 4.50  # not the "from $0.79" floor
    assert find(rows, gpu_model="B300").usd_per_gpu_hour == 9.50
    assert all(o.pricing == "on_demand" for o in rows)
    assert not any(o.gpu_model == "L40S" for o in rows)  # "from $X" rows skipped


def test_nebius_price_column_logic() -> None:
    from datetime import date

    from gpu_index.sources.nebius import price_column

    headers = ["Item", "vCPUs", "On-demand, GPU-hour", "GPU-hour (Effective October 1, 2026)"]
    assert price_column(headers, date(2026, 9, 30)) == 2
    assert price_column(headers, date(2026, 10, 1)) == 3
    assert price_column(["Item", "Price"], date(2026, 10, 1)) is None
    headers = ["Item", "vCPUs", "Preemptible, GPU-hour *", "On-demand, GPU-hour"]
    assert price_column(headers, date(2026, 10, 23)) == 3


def test_crusoe_reads_on_demand_column_and_skips_inference_endpoints() -> None:
    rows = parse("crusoe")
    assert len([o for o in rows if o.gpu_model == "H100"]) == 1  # not the $5.50 endpoint
    assert find(rows, gpu_model="H100").usd_per_gpu_hour == 3.90  # not the Dec 1 price, $4.50
    assert find(rows, gpu_model="H200").usd_per_gpu_hour == 4.29
    assert not any(o.gpu_model == "B200" for o in rows)  # instance is "Contact sales"
    assert find(rows, gpu_model="A100-80GB").usd_per_gpu_hour == 2.30
    assert find(rows, gpu_model="A100-80GB-PCIe").usd_per_gpu_hour == 2.00
    assert {o.gpu_model for o in rows} == {
        "B300",
        "H200",
        "H100",
        "A100-80GB",
        "A100-80GB-PCIe",
        "L40S",
        "MI300X",
    }


def test_crusoe_reads_plain_on_demand_header() -> None:
    from gpu_index.sources.crusoe import parse as parse_crusoe

    def column(*cells: str) -> str:
        items = "".join(f'<div class="w-dyn-item">{c}</div>' for c in cells)
        return f'<div class="w-dyn-list">{items}</div>'

    html = (
        '<div class="table-wr-h"><div class="pricing-table-heading">'
        "<div>GPU model</div><div>On-demand</div></div>"
        + column(
            '<div class="pricing-item-heading">NVIDIA H100</div>'
            '<div class="pricing-tag">80GB</div><div class="pricing-tag">HGX</div>'
        )
        + column("$4.50 / GPU-hr")
        + "</div>"
    )
    assert [(o.gpu_model, o.usd_per_gpu_hour) for o in parse_crusoe(html, STAMP)] == [("H100", 4.5)]


def test_hyperstack_maps_pcie_cards_explicitly_and_ignores_reservations() -> None:
    rows = parse("hyperstack")
    assert find(rows, sku="NVIDIA H100", pricing="on_demand").gpu_model == "H100-PCIe"
    assert find(rows, sku="NVIDIA H100 SXM", pricing="on_demand").usd_per_gpu_hour == 3.20
    assert {o.pricing for o in rows} == {"on_demand", "spot"}
    assert not any(o.usd_per_gpu_hour == 2.72 for o in rows)  # reservation price


def test_oracle_maps_part_numbers_and_skips_lookalikes() -> None:
    rows = parse("oracle")
    assert find(rows, gpu_model="H100").usd_per_gpu_hour == 10.0
    assert find(rows, gpu_model="A100-80GB").sku == "BM.GPU.A100-v2.8"
    # Cloud@Customer L40S and NVIDIA AI Enterprise licences share names but aren't rentals.
    assert len([o for o in rows if o.gpu_model == "L40S"]) == 1
    assert all(o.segment == "hyperscaler" and o.pricing == "on_demand" for o in rows)


def test_gcp_reads_columns_by_header_and_normalizes_machine_types() -> None:
    rows = parse("gcp")
    a3 = find(rows, sku="a3-highgpu-8g", pricing="on_demand")
    assert (a3.gpu_model, a3.gpu_count, a3.usd_per_hour) == ("H100", 8, 88.49)
    assert find(rows, sku="a3-highgpu-8g", pricing="spot").usd_per_gpu_hour < a3.usd_per_gpu_hour
    assert find(rows, sku="a2-highgpu-1g", pricing="on_demand").gpu_model == "A100-40GB"
    assert find(rows, sku="a2-ultragpu-1g", pricing="on_demand").gpu_model == "A100-80GB"
    # A4 (B200) on-demand is "N/A" on the page: spot only.
    assert [o.pricing for o in rows if o.gpu_model == "B200"] == ["spot"]
    assert {o.region for o in rows} == {"us-central1"}
