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
    ]
    rows = ADAPTERS["vast"].parse(offers, STAMP)
    assert {o.gpu_model: o.usd_per_gpu_hour for o in rows} == {"A100-40GB": 0.8, "A100-80GB": 1.5}
