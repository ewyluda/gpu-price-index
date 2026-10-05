"""Google Cloud accelerator-optimized VM prices from its public pricing page.

The page renders one table of GPU machine types for the region selected by default,
Iowa (us-central1), with on-demand, DWS, spot and committed-use columns. Columns are
located by header text rather than position or CSS class (Google's class names are
generated). DWS (Dynamic Workload Scheduler) and CUD prices are not on-demand list
prices and are ignored.

Google's official Cloud Billing Catalog API would cover every region but needs an
API key; this keyless route covers one region, which is noted in the methodology.
"""

from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup, Tag

from gpu_index.http import get
from gpu_index.models import Observation, Pricing
from gpu_index.sources.base import SourceAdapter, Stamp, observation

URL = "https://cloud.google.com/products/compute/pricing/accelerator-optimized"
PROVIDER = "Google Cloud"
REGION = "us-central1"

# machine-type prefix -> catalog key (the suffix "-Ng" gives the GPU count)
FAMILIES: dict[str, str] = {
    "a4-highgpu": "B200",
    "a3-ultragpu": "H200",
    "a3-megagpu": "H100",
    "a3-highgpu": "H100",
    "a2-ultragpu": "A100-80GB",
    "a2-highgpu": "A100-40GB",
    "a2-megagpu": "A100-40GB",
}
COLUMNS: dict[Pricing, str] = {"on_demand": "Price (USD)", "spot": "Current Spot pricing"}
_MACHINE = re.compile(r"^([a-z0-9]+-[a-z]+gpu)-(\d+)g$")
_PRICE = re.compile(r"\$([\d,]+(?:\.\d+)?)\s*/\s*1 hour")


def fetch(client: httpx.Client) -> str:
    return get(client, URL).text


def _cells(row: Tag) -> list[str]:
    return [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]


def parse(html: str, stamp: Stamp) -> list[Observation]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[Observation] = []
    for table in soup.find_all("table"):
        trs = table.find_all("tr")
        header = _cells(trs[0]) if trs else []
        if not header or header[0] != "Machine type":
            continue
        index = {
            pricing: next((i for i, h in enumerate(header) if h.startswith(label)), None)
            for pricing, label in COLUMNS.items()
        }
        for tr in trs[1:]:
            cells = _cells(tr)
            machine = _MACHINE.match(cells[0]) if cells else None
            gpu_model = FAMILIES.get(machine.group(1)) if machine else None
            if machine is None or gpu_model is None:
                continue
            for pricing, i in index.items():
                price = _PRICE.search(cells[i]) if i is not None and i < len(cells) else None
                if price is None:  # "N/A": not sold this way
                    continue
                rows.append(
                    observation(
                        stamp,
                        source="gcp",
                        provider=PROVIDER,
                        segment="hyperscaler",
                        pricing=pricing,
                        gpu_model=gpu_model,
                        sku=cells[0],
                        region=REGION,
                        geo="NA",
                        gpu_count=int(machine.group(2)),
                        usd_per_hour=float(price.group(1).replace(",", "")),
                    )
                )
    return rows


ADAPTER = SourceAdapter(
    id="gcp",
    name=PROVIDER,
    homepage=URL,
    terms="Public pricing page; Google's terms restrict automated access only where it "
    "violates robots.txt, which allows this page. One request per day.",
    min_rows=6,
    fetch=fetch,
    parse=parse,
)
