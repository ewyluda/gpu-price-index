"""Registry of price sources, grouped by market segment."""

from gpu_index.sources import (
    aws,
    azure,
    coreweave,
    crusoe,
    hyperstack,
    lambda_cloud,
    nebius,
    runpod,
    vast,
)
from gpu_index.sources.base import SourceAdapter, Stamp

ADAPTERS: dict[str, SourceAdapter] = {
    adapter.id: adapter
    for adapter in [
        # hyperscalers
        azure.ADAPTER,
        aws.ADAPTER,
        # neoclouds
        coreweave.ADAPTER,
        nebius.ADAPTER,
        crusoe.ADAPTER,
        lambda_cloud.ADAPTER,
        hyperstack.ADAPTER,
        # neocloud + marketplace
        runpod.ADAPTER,
        # marketplace
        vast.ADAPTER,
    ]
}

__all__ = ["ADAPTERS", "SourceAdapter", "Stamp"]
