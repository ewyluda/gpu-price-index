"""Core record type shared by every source adapter, the store, and the index."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any, Literal

Segment = Literal["hyperscaler", "neocloud", "marketplace"]
Pricing = Literal["on_demand", "spot"]

SEGMENTS: tuple[Segment, ...] = ("hyperscaler", "neocloud", "marketplace")
PRICING: tuple[Pricing, ...] = ("on_demand", "spot")


@dataclass(frozen=True, slots=True)
class Observation:
    """One published price for one SKU in one region on one day.

    ``usd_per_gpu_hour`` is the normalized unit every downstream calculation uses;
    ``usd_per_hour`` keeps the instance-level list price for auditability.
    Marketplace sources (Vast.ai) publish thousands of individual offers, so they
    are summarized to one median observation per GPU model with ``sample_size`` set.
    """

    date: str  # YYYY-MM-DD (UTC) of collection
    collected_at: str  # ISO-8601 UTC timestamp
    source: str  # adapter id, e.g. "azure"
    provider: str  # display name, e.g. "Microsoft Azure"
    segment: Segment
    pricing: Pricing
    gpu_model: str  # canonical key from catalog.GPUS
    sku: str
    region: str
    geo: str  # NA | EU | APAC | ME | LATAM | Global
    gpu_count: int
    usd_per_hour: float
    usd_per_gpu_hour: float
    sample_size: int = 1

    @property
    def key(self) -> tuple[str, ...]:
        """Natural key: one price per SKU/region/pricing type per provider per day."""
        return (
            self.date,
            self.source,
            self.provider,
            self.pricing,
            self.gpu_model,
            self.sku,
            self.region,
        )

    def to_row(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: dict[str, str]) -> Observation:
        return cls(
            date=row["date"],
            collected_at=row["collected_at"],
            source=row["source"],
            provider=row["provider"],
            segment=row["segment"],  # type: ignore[arg-type]
            pricing=row["pricing"],  # type: ignore[arg-type]
            gpu_model=row["gpu_model"],
            sku=row["sku"],
            region=row["region"],
            geo=row["geo"],
            gpu_count=int(row["gpu_count"]),
            usd_per_hour=float(row["usd_per_hour"]),
            usd_per_gpu_hour=float(row["usd_per_gpu_hour"]),
            sample_size=int(row.get("sample_size") or 1),
        )


FIELDNAMES: list[str] = [f.name for f in fields(Observation)]
