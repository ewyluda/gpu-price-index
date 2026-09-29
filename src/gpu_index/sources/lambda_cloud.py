"""Lambda on-demand instance prices from its public pricing page.

Lambda's API requires an account key, but the pricing page renders a semantic table
(``tr[data-plan]`` rows with ``data-label`` cells), which is stable enough to parse.
Lambda's terms permit crawling that is rate-limited; we make one request per day.
"""

from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup, Tag

from gpu_index.catalog import normalize_gpu_name
from gpu_index.http import get
from gpu_index.models import Observation
from gpu_index.sources.base import SourceAdapter, Stamp, observation

URL = "https://lambda.ai/pricing"
PROVIDER = "Lambda"
PRICE_LABEL = "PRICE/GPU/HR*"
# On-demand instance tables are rendered as tabs in this order.
TAB_GPU_COUNTS = [8, 4, 2, 1]


def fetch(client: httpx.Client) -> str:
    return get(client, URL).text


def _cell(row: Tag, label: str) -> str:
    cell = row.find("td", attrs={"data-label": label})
    return cell.get_text(strip=True) if cell else ""


def parse(html: str, stamp: Stamp) -> list[Observation]:
    soup = BeautifulSoup(html, "html.parser")
    # Instance tables have a VRAM column; cluster/reserved tables do not.
    tables = [t for t in soup.find_all("table") if t.find("td", attrs={"data-label": "VRAM/GPU"})]
    counts = TAB_GPU_COUNTS if len(tables) == len(TAB_GPU_COUNTS) else [1] * len(tables)

    rows: list[Observation] = []
    for table, count in zip(tables, counts, strict=True):
        for row in table.select("tr[data-plan]"):
            plan = str(row["data-plan"])
            vram = _cell(row, "VRAM/GPU")
            gpu_model = normalize_gpu_name(f"{plan} {vram.replace(' ', '')}")
            match = re.search(r"\$([\d.]+)", _cell(row, PRICE_LABEL))
            if gpu_model is None or match is None:
                continue
            per_gpu = float(match.group(1))
            slug = re.sub(r"[^a-z0-9]+", "_", plan.lower().removeprefix("nvidia ")).strip("_")
            rows.append(
                observation(
                    stamp,
                    source="lambda",
                    provider=PROVIDER,
                    segment="neocloud",
                    pricing="on_demand",
                    gpu_model=gpu_model,
                    sku=f"gpu_{count}x_{slug}_{vram.replace(' ', '').lower()}",
                    region="global",
                    geo="Global",
                    gpu_count=count,
                    usd_per_hour=per_gpu * count,
                )
            )
    return rows


ADAPTER = SourceAdapter(
    id="lambda",
    name=PROVIDER,
    homepage=URL,
    terms="Public pricing page; Lambda's terms allow rate-limited crawling (1 request/day).",
    min_rows=3,
    fetch=fetch,
    parse=parse,
)
