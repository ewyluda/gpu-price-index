"""CoreWeave on-demand and spot instance prices from its public pricing page.

The page renders one ``.table-grid`` per instance type: a model heading with a stable
``data-product`` slug, the GPU count, and ``.instance-price`` / ``.spot-price``
values for the whole instance. The product list appears twice on the page (general
and Kubernetes listings), so each product is taken once.
"""

from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup, Tag

from gpu_index.catalog import normalize_gpu_name
from gpu_index.http import get
from gpu_index.models import Observation, Pricing
from gpu_index.sources.base import SourceAdapter, Stamp, observation

URL = "https://www.coreweave.com/pricing"
PROVIDER = "CoreWeave"


def fetch(client: httpx.Client) -> str:
    return get(client, URL).text


def _price(grid: Tag, selector: str) -> float | None:
    node = grid.select_one(f"{selector} .item-value")
    match = re.search(r"\$([\d,]+(?:\.\d+)?)", node.get_text() if node else "")
    return float(match.group(1).replace(",", "")) if match else None


def parse(html: str, stamp: Stamp) -> list[Observation]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[Observation] = []
    seen: set[str] = set()
    for grid in soup.select(".table-grid"):
        heading = grid.select_one("h3.table-model-name[data-product]")
        cells = grid.select(".table-v2-cell")
        if heading is None or len(cells) < 2:
            continue
        product = str(heading["data-product"])
        gpu_model = normalize_gpu_name(heading.get_text(strip=True))
        count = re.match(r"\d+", cells[1].get_text(strip=True))
        if product in seen or gpu_model is None or count is None:
            continue
        seen.add(product)
        offers: list[tuple[Pricing, str]] = [
            ("on_demand", ".instance-price"),
            ("spot", ".spot-price"),
        ]
        for pricing, selector in offers:
            price = _price(grid, selector)
            if price is None:  # "N/A" or blank: not offered this way
                continue
            rows.append(
                observation(
                    stamp,
                    source="coreweave",
                    provider=PROVIDER,
                    segment="neocloud",
                    pricing=pricing,
                    gpu_model=gpu_model,
                    sku=product,
                    region="global",
                    geo="Global",
                    gpu_count=int(count.group()),
                    usd_per_hour=price,
                )
            )
    return rows


ADAPTER = SourceAdapter(
    id="coreweave",
    name=PROVIDER,
    homepage=URL,
    terms="Public pricing page; robots.txt allows it and the terms of service have no "
    "crawling restriction. One request per day.",
    min_rows=4,
    fetch=fetch,
    parse=parse,
)
