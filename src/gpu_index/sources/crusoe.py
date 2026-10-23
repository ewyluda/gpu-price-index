"""Crusoe Cloud on-demand GPU prices from its public pricing page.

The GPU table is laid out column by column: a list of GPU names (a model heading
plus form-factor tags such as "80GB", "SXM", "PCIe", "HGX") and, beside it, one list
per pricing type, matched by position. Columns are found by their header text
("GPU model", "On-demand") rather than order or class names. Prices are written as
"$3.90 / GPU-hr"; "Contact sales" cells are skipped, and other tables on the page
(CPU instances, inference endpoints) don't have a "GPU model" column.
"""

from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup

from gpu_index.catalog import normalize_gpu_name
from gpu_index.http import get
from gpu_index.models import Observation
from gpu_index.sources.base import SourceAdapter, Stamp, observation

URL = "https://crusoe.ai/cloud/pricing"
PROVIDER = "Crusoe"
_PER_GPU_HOUR = re.compile(r"\$(\d+(?:\.\d+)?)\s*/\s*GPU-hr")


def fetch(client: httpx.Client) -> str:
    return get(client, URL).text


def parse(html: str, stamp: Stamp) -> list[Observation]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[Observation] = []
    for table in soup.select(".table-wr-h"):
        headers = [h.get_text(" ", strip=True) for h in table.select(".pricing-table-heading > *")]
        columns = table.select(".w-dyn-list")
        if headers[:1] != ["GPU model"] or "On-demand" not in headers:
            continue
        if len(columns) != len(headers):
            raise ValueError(f"Crusoe GPU table has {len(headers)} headers, {len(columns)} columns")
        names = columns[0].select(".w-dyn-item")
        prices = columns[headers.index("On-demand")].select(".w-dyn-item")
        for name, price in zip(names, prices, strict=True):
            heading = name.select_one(".pricing-item-heading")
            if heading is None:
                continue
            tags = [t.get_text(strip=True) for t in name.select(".pricing-tag")]
            label = " ".join([heading.get_text(strip=True), *tags])
            gpu_model = normalize_gpu_name(label)
            on_demand = _PER_GPU_HOUR.search(price.get_text(" ", strip=True))
            if gpu_model is None or on_demand is None:
                continue
            rows.append(
                observation(
                    stamp,
                    source="crusoe",
                    provider=PROVIDER,
                    segment="neocloud",
                    pricing="on_demand",
                    gpu_model=gpu_model,
                    sku=label,
                    region="global",
                    geo="Global",
                    gpu_count=1,
                    usd_per_hour=float(on_demand.group(1)),
                )
            )
    return rows


ADAPTER = SourceAdapter(
    id="crusoe",
    name=PROVIDER,
    homepage=URL,
    terms="Public pricing page; robots.txt allows it and the legal terms have no crawling "
    "restriction. One request per day.",
    min_rows=3,
    fetch=fetch,
    parse=parse,
)
