"""Registry of price sources, grouped by market segment."""

from gpu_index.sources import aws, azure, lambda_cloud, runpod, vast
from gpu_index.sources.base import SourceAdapter, Stamp

ADAPTERS: dict[str, SourceAdapter] = {
    adapter.id: adapter
    for adapter in [
        azure.ADAPTER,
        aws.ADAPTER,
        lambda_cloud.ADAPTER,
        runpod.ADAPTER,
        vast.ADAPTER,
    ]
}

__all__ = ["ADAPTERS", "SourceAdapter", "Stamp"]
