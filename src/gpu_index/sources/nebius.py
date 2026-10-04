"""Nebius AI Cloud on-demand GPU prices from its public price list.

Nebius publishes price changes ahead of time as an extra column, e.g. "GPU-hour
(Effective October 1, 2026)". The parser picks the latest column whose effective
date has arrived by the collection date, so announced changes switch over on the
right day without a code change. "from $X" prices (configurable instances) and
"Contact us" rows aren't comparable list prices and are skipped.
"""

from __future__ import annotations

import re
from datetime import date, datetime

import httpx
from bs4 import BeautifulSoup, Tag

from gpu_index.catalog import normalize_gpu_name
from gpu_index.http import get
from gpu_index.models import Observation
from gpu_index.sources.base import SourceAdapter, Stamp, observation

URL = "https://nebius.com/prices"
PROVIDER = "Nebius"
TABLE_TITLE = "NVIDIA GPU Instances"
_EFFECTIVE = re.compile(r"Effective (\w+ \d{1,2}, \d{4})")


def fetch(client: httpx.Client) -> str:
    return get(client, URL).text


def _cells(row: Tag) -> list[str]:
    return [c.get_text(" ", strip=True) for c in row.select(".pc-highlight-table-block__cell")]


def price_column(headers: list[str], today: date) -> int | None:
    """Index of the GPU-hour price column in force on ``today``."""
    current: int | None = None
    for i, header in enumerate(headers):
        if "GPU-hour" not in header:
            continue
        effective = _EFFECTIVE.search(header)
        if effective is None:
            if current is None:
                current = i
        elif datetime.strptime(effective.group(1), "%B %d, %Y").date() <= today:
            current = i  # a later effective column supersedes the standing price
    return current


def parse(html: str, stamp: Stamp) -> list[Observation]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[Observation] = []
    for block in soup.select(".pc-highlight-table-block__content"):
        title = block.find_previous(["h2", "h3", "h4"])
        if title is None or title.get_text(" ", strip=True) != TABLE_TITLE:
            continue
        table = [_cells(r) for r in block.select(".pc-highlight-table-block__row")]
        if not table:
            continue
        column = price_column(table[0], date.fromisoformat(stamp.date))
        if column is None:
            continue
        for cells in table[1:]:
            gpu_model = normalize_gpu_name(cells[0])
            price = (
                re.fullmatch(r"\$(\d+(?:\.\d+)?)", cells[column]) if column < len(cells) else None
            )
            if gpu_model is None or price is None:
                continue
            rows.append(
                observation(
                    stamp,
                    source="nebius",
                    provider=PROVIDER,
                    segment="neocloud",
                    pricing="on_demand",
                    gpu_model=gpu_model,
                    sku=cells[0],
                    region="global",
                    geo="Global",
                    gpu_count=1,
                    usd_per_hour=float(price.group(1)),
                )
            )
    return rows


ADAPTER = SourceAdapter(
    id="nebius",
    name=PROVIDER,
    homepage=URL,
    terms="Public price list; robots.txt allows it and the terms of use have no crawling "
    "restriction. One request per day.",
    min_rows=3,
    fetch=fetch,
    parse=parse,
)
