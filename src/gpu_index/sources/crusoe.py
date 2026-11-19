"""Crusoe Cloud on-demand GPU prices from its public pricing page.

The GPU table is laid out column by column: a list of GPU names (a model heading
plus form-factor tags such as "80GB", "SXM", "PCIe", "HGX") and, beside it, one list
per pricing type, matched by position. Columns are found by their header text
("GPU model", "On-demand") rather than order or class names. Ahead of a price change
the page relabels the column "Current on-demand" and adds one for the new prices
("New on-demand starting Dec 1, 2026"). The new column is read once its start date has
arrived by the collection date (a "No change" cell keeps the current price), so the
change lands on the right day even if the page still shows both columns. Prices are
written as "$3.90 / GPU-hr"; "Contact sales" cells are skipped, and other tables on the page
(CPU instances, inference endpoints) don't have a "GPU model" column.
"""

from __future__ import annotations

import re
from datetime import date, datetime

import httpx
from bs4 import BeautifulSoup

from gpu_index.catalog import normalize_gpu_name
from gpu_index.http import get
from gpu_index.models import Observation
from gpu_index.sources.base import SourceAdapter, Stamp, observation

URL = "https://crusoe.ai/cloud/pricing"
PROVIDER = "Crusoe"
_PER_GPU_HOUR = re.compile(r"\$(\d+(?:\.\d+)?)\s*/\s*GPU-hr")
_ON_DEMAND = re.compile(r"(?:Current )?On-demand", re.IGNORECASE)
_NEW_ON_DEMAND = re.compile(r"New on-demand starting (\w+ \d{1,2}, \d{4})", re.IGNORECASE)


def _new_column(headers: list[str], today: date) -> int | None:
    """Index of an announced on-demand column whose start date has arrived, if any."""
    for i, header in enumerate(headers):
        starts = _NEW_ON_DEMAND.fullmatch(header)
        if starts and _parse_date(starts.group(1)) <= today:
            return i
    return None


def _parse_date(text: str) -> date:
    try:
        return datetime.strptime(text, "%b %d, %Y").date()  # "Dec 1, 2026"
    except ValueError:
        return datetime.strptime(text, "%B %d, %Y").date()  # "December 1, 2026"


def fetch(client: httpx.Client) -> str:
    return get(client, URL).text


def parse(html: str, stamp: Stamp) -> list[Observation]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[Observation] = []
    for table in soup.select(".table-wr-h"):
        headers = [h.get_text(" ", strip=True) for h in table.select(".pricing-table-heading > *")]
        columns = table.select(".w-dyn-list")
        on_demand_col = next((i for i, h in enumerate(headers) if _ON_DEMAND.fullmatch(h)), None)
        if headers[:1] != ["GPU model"] or on_demand_col is None:
            continue
        if len(columns) != len(headers):
            raise ValueError(f"Crusoe GPU table has {len(headers)} headers, {len(columns)} columns")
        names = columns[0].select(".w-dyn-item")
        prices = [p.get_text(" ", strip=True) for p in columns[on_demand_col].select(".w-dyn-item")]
        new_col = _new_column(headers, date.fromisoformat(stamp.date))
        if new_col is not None:
            announced = [
                p.get_text(" ", strip=True) for p in columns[new_col].select(".w-dyn-item")
            ]
            prices = [
                old if "no change" in new.lower() else new
                for old, new in zip(prices, announced, strict=True)
            ]
        for name, price in zip(names, prices, strict=True):
            heading = name.select_one(".pricing-item-heading")
            if heading is None:
                continue
            tags = [t.get_text(strip=True) for t in name.select(".pricing-tag")]
            label = " ".join([heading.get_text(strip=True), *tags])
            gpu_model = normalize_gpu_name(label)
            on_demand = _PER_GPU_HOUR.search(price)
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
