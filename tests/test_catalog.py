import pytest

from gpu_index.catalog import GPUS, geo_for_region, normalize_gpu_name


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("H100 SXM", "H100"),
        ("NVIDIA H100 80GB HBM3", "H100"),
        ("H100 PCIE", "H100-PCIe"),
        ("NVIDIA H100 NVL", "H100-NVL"),
        ("H200 SXM", "H200"),
        ("NVIDIA A100-SXM4-40GB", "A100-40GB"),
        ("NVIDIA A100 80GB PCIe", "A100-80GB-PCIe"),
        ("A100 SXM4 80GB", "A100-80GB"),
        ("AMD Instinct MI300X OAM", "MI300X"),
        ("NVIDIA B300 SXM6 AC", "B300"),
        ("L40S", "L40S"),
        ("RTX 4090", None),
        ("H200 NVL", None),  # untracked variant: must not be folded into H200
    ],
)
def test_normalize_gpu_name(label: str, expected: str | None) -> None:
    assert normalize_gpu_name(label) == expected


@pytest.mark.parametrize(
    ("region", "geo"),
    [
        ("eastus", "NA"),
        ("US East (N. Virginia)", "NA"),
        ("westeurope", "EU"),
        ("Europe (Frankfurt)", "EU"),
        ("southeastasia", "APAC"),
        ("australiaeast", "APAC"),  # contains "us" - APAC must win
        ("Asia Pacific (Tokyo)", "APAC"),
        ("uaenorth", "ME"),
        ("brazilsouth", "LATAM"),
        ("South America (Sao Paulo)", "LATAM"),
        ("southafricanorth", "AF"),
        ("global", "Global"),
    ],
)
def test_geo_for_region(region: str, geo: str) -> None:
    assert geo_for_region(region) == geo


def test_every_catalog_entry_has_positive_specs() -> None:
    for spec in GPUS.values():
        assert spec.memory_gb > 0 and spec.bf16_dense_tflops > 0 and spec.bandwidth_tbps > 0
