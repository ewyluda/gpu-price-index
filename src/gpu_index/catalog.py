"""Canonical GPU models, their specs, and name normalization.

Every source names the same silicon differently ("H100 SXM", "NVIDIA H100 80GB HBM3",
"p5.48xlarge", "Standard_ND96isr_H100_v5"). Adapters map to the keys below so that
prices are compared like-for-like. Form factor is part of the key where it changes
performance or price materially (SXM vs PCIe vs NVL).
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GPUSpec:
    key: str
    name: str
    vendor: str
    generation: str
    memory_gb: int
    bandwidth_tbps: float
    bf16_dense_tflops: float  # vendor-published peak, no sparsity
    headline: bool  # shown as a headline index on the dashboard


GPUS: dict[str, GPUSpec] = {
    spec.key: spec
    for spec in [
        GPUSpec("B300", "B300", "NVIDIA", "Blackwell Ultra", 288, 8.0, 2250, False),
        GPUSpec("B200", "B200", "NVIDIA", "Blackwell", 180, 7.7, 2250, True),
        GPUSpec("H200", "H200", "NVIDIA", "Hopper", 141, 4.8, 989, True),
        GPUSpec("H100", "H100 SXM", "NVIDIA", "Hopper", 80, 3.35, 989, True),
        GPUSpec("H100-NVL", "H100 NVL", "NVIDIA", "Hopper", 94, 3.9, 835, False),
        GPUSpec("H100-PCIe", "H100 PCIe", "NVIDIA", "Hopper", 80, 2.0, 756, False),
        GPUSpec("MI300X", "MI300X", "AMD", "CDNA 3", 192, 5.3, 1307, True),
        GPUSpec("A100-80GB", "A100 80GB SXM", "NVIDIA", "Ampere", 80, 2.04, 312, True),
        GPUSpec("A100-80GB-PCIe", "A100 80GB PCIe", "NVIDIA", "Ampere", 80, 1.94, 312, False),
        GPUSpec("A100-40GB", "A100 40GB", "NVIDIA", "Ampere", 40, 1.56, 312, False),
        GPUSpec("L40S", "L40S", "NVIDIA", "Ada Lovelace", 48, 0.86, 362, True),
    ]
}

# Ordered patterns: first match wins, so more specific variants come first.
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(p, re.IGNORECASE), key)
    for p, key in [
        (r"\bB300\b", "B300"),
        (r"\bB200\b", "B200"),
        (r"\bH200\b(?!.*\bNVL\b)", "H200"),
        (r"\bH100\b.*\bNVL\b", "H100-NVL"),
        (r"\bH100\b.*\bPCIe?\b", "H100-PCIe"),
        (r"\bH100\b", "H100"),
        (r"\bMI300X\b", "MI300X"),
        (r"\bA100\b.*\b40\s?GB\b", "A100-40GB"),
        (r"\bA100\b.*\bPCIe?\b", "A100-80GB-PCIe"),
        (r"\bA100\b", "A100-80GB"),
        (r"\bL40S\b", "L40S"),
    ]
]


def normalize_gpu_name(name: str) -> str | None:
    """Map a vendor-specific GPU label to a catalog key, or None if untracked."""
    for pattern, key in _PATTERNS:
        if pattern.search(name):
            return key
    return None


# Checked in order against the region label with spaces/punctuation removed, so both
# Azure codes ("southeastasia") and AWS names ("Asia Pacific (Tokyo)") resolve.
# Order matters: "australia" contains "us", so APAC is checked before NA.
_GEO_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("ME", ("uae", "qatar", "israel", "middleeast", "saudi", "bahrain")),
    ("AF", ("africa",)),
    ("LATAM", ("brazil", "mexico", "chile", "southamerica", "saopaulo")),
    (
        "APAC",
        (
            "asia",
            "japan",
            "korea",
            "australia",
            "india",
            "singapore",
            "hongkong",
            "tokyo",
            "osaka",
            "seoul",
            "sydney",
            "melbourne",
            "jakarta",
            "taiwan",
            "indonesia",
            "malaysia",
            "newzealand",
            "mumbai",
        ),
    ),
    (
        "EU",
        (
            "europe",
            "uk",
            "france",
            "germany",
            "sweden",
            "norway",
            "poland",
            "switzerland",
            "italy",
            "spain",
            "ireland",
            "london",
            "frankfurt",
            "paris",
            "stockholm",
            "milan",
            "zurich",
            "netherlands",
            "finland",
            "iceland",
            "czech",
            "belgium",
            "austria",
            "denmark",
            "portugal",
        ),
    ),
    ("NA", ("us", "canada", "virginia", "ohio", "oregon", "california", "texas")),
]


def geo_for_region(region: str) -> str:
    """Bucket a provider region label into a coarse geography (NA, EU, APAC, ...)."""
    text = re.sub(r"[^a-z]", "", region.lower())
    for geo, needles in _GEO_RULES:
        if any(needle in text for needle in needles):
            return geo
    return "Global"
