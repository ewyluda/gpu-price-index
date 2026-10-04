# Methodology

*Methodology version 1.1 · history begins 2026-09-29*

The GPU Price Index answers one question: **what does an hour of a given GPU cost to rent
today, and how does that depend on where you rent it?** This document describes what's
collected, how it's normalized and aggregated, what's checked, and what the numbers don't
tell you.

## 1. What's measured

- **Unit:** US dollars per GPU-hour, on-demand list price, compute only. An 8-GPU VM
  listed at $98.32/hr is recorded as $98.32 instance-hours *and* $12.29 per GPU-hour.
- **Pricing types:** `on_demand` (the index) and `spot` (a separate series, from Azure,
  CoreWeave and Hyperstack). Reserved and committed-use prices aren't published and aren't included.
- **Frequency:** one collection per day at 06:17 UTC. The collection date (UTC) is the
  observation date.

### GPUs tracked

Form factor is part of the model key wherever it changes price or performance (SXM and
PCIe H100s aren't the same product).

| Key | Name | Memory | Bandwidth | BF16 dense |
|---|---|---|---|---|
| `B300` | B300 | 288 GB | 8.0 TB/s | 2,250 TFLOPS |
| `B200` | B200 | 180 GB | 7.7 TB/s | 2,250 TFLOPS |
| `H200` | H200 | 141 GB | 4.8 TB/s | 989 TFLOPS |
| `H100` | H100 SXM | 80 GB | 3.35 TB/s | 989 TFLOPS |
| `H100-NVL` | H100 NVL | 94 GB | 3.9 TB/s | 835 TFLOPS |
| `H100-PCIe` | H100 PCIe | 80 GB | 2.0 TB/s | 756 TFLOPS |
| `MI300X` | MI300X | 192 GB | 5.3 TB/s | 1,307 TFLOPS |
| `A100-80GB` | A100 80GB SXM | 80 GB | 2.04 TB/s | 312 TFLOPS |
| `A100-80GB-PCIe` | A100 80GB PCIe | 80 GB | 1.94 TB/s | 312 TFLOPS |
| `A100-40GB` | A100 40GB | 40 GB | 1.56 TB/s | 312 TFLOPS |
| `L40S` | L40S | 48 GB | 0.86 TB/s | 362 TFLOPS |

Specs are vendor-published peak figures without sparsity (`src/gpu_index/catalog.py`).
B300 dense BF16 is listed at parity with B200. Blackwell Ultra's gains are concentrated in
FP4.

## 2. Sources and segments

Providers are grouped into three market segments, because *who* you rent from moves the
price more than any other factor.

| Segment | Source | What's collected | Access |
|---|---|---|---|
| Hyperscaler | **Microsoft Azure** | ND/NC GPU VM series, every public region, on-demand and spot | [Retail Prices API](https://learn.microsoft.com/rest/api/cost-management/retail-prices/azure-retail-prices) (public, no key) |
| Hyperscaler | **AWS** | P4d/P4de/P5/P5e/P5en/P6 and G6e instances in 10 regions | Per-region pricing documents behind aws.amazon.com/ec2/pricing |
| Neocloud | **CoreWeave** | HGX/PCIe instances, on-demand and spot | Public pricing page |
| Neocloud | **Nebius** | GPU instances, on-demand (applies announced price changes on their effective date) | Public price list |
| Neocloud | **Crusoe** | GPU instances, on-demand | Public pricing page |
| Neocloud | **Lambda** | On-demand instances, 1×/2×/4×/8× shapes | Public pricing page (Lambda's terms allow rate-limited crawling) |
| Neocloud | **Hyperstack** | GPU VMs, on-demand and spot | Public pricing page |
| Neocloud | **RunPod Secure Cloud** | Per-GPU secure-cloud price | Public GraphQL API, no key |
| Marketplace | **RunPod Community Cloud** | Per-GPU community price | Same API |
| Marketplace | **Vast.ai** | Every rentable on-demand offer for each tracked GPU | Public offer-search API |

Every source is a public price list published for buyers to read. No source requires
authentication, and none is a third-party index or aggregator. Before a source is added,
its robots.txt and terms are checked for restrictions on automated access, and each page is
fetched once per day with an identifying User-Agent.

| Excluded | Reason |
|---|---|
| Together AI | robots.txt disallows all crawlers |
| Verda (formerly DataCrunch) | Terms list scrapers among prohibited automated uses |
| Third-party GPU price indices | Proprietary data; terms prohibit storage and redistribution |

### Normalization rules

- **Azure:** Linux, pay-as-you-go (`Consumption`) meters only. Windows, Low Priority,
  DevTest and sovereign-cloud regions (`usgov*`, `usdod*`) are excluded. Azure publishes spot
  meters at the full on-demand rate in some regions where spot isn't really discounted, so a
  spot row priced at or above the same SKU's on-demand price is dropped. Flex/no-InfiniBand
  variants of a VM shape are skipped, because they carry the same GPU and would double-count.
- **AWS:** one row per instance type per region. `p5.4xlarge` (1× H100) and `p5.48xlarge`
  (8× H100) both count, and the provider median absorbs the shape difference.
- **Lambda:** the per-GPU price is read directly. The instance count comes from the tab order
  (8×, 4×, 2×, 1×). If the page ever shows a different number of tabs, counts fall back to 1
  rather than guessing.
- **RunPod:** a price of 0 means "not offered in this cloud" and is skipped.
- **Vast.ai:** a marketplace has no list price, so every rentable on-demand offer is
  normalized to per-GPU price and summarized as **one median observation per GPU model**,
  with `sample_size` = number of offers. Vast reports "A100 SXM4" for both memory sizes, so
  offers are split on reported VRAM.

## 3. Aggregation

### Two-stage median

For each GPU and day:

1. **Provider median:** the median per-GPU on-demand price across that provider's SKUs and
   regions.
2. **Index:** the median of those provider medians.

Stage 1 gives each provider one vote. Without it, Azure's ~20 regional rows per SKU would
outvote Lambda's single price list, and the index would mostly measure Azure. Stage 2 makes
the index robust to any single provider's outlier price. Medians are used rather than means
throughout for the same reason.

| Series | Definition |
|---|---|
| **Market index** | Median of provider medians, all segments |
| **Hyperscaler / Neocloud / Marketplace** | Median of provider medians within the segment |
| **Spot** | Median of provider spot medians, all segments |
| **Hyperscaler premium** | `hyperscaler / neocloud − 1` for the same GPU and day |
| **7-day / 30-day change** | Latest value vs. the last value on or before *latest − N days*, **recomputed over the providers listed on both dates** (see below); blank until enough history exists |
| **Regional** | Median of region-specific list prices per geography (NA, EU, APAC, ME, LATAM, AF). Global list prices (neoclouds, marketplaces) are excluded |
| **$/PFLOP-hr** | Market index ÷ (BF16 dense TFLOPS ÷ 1000) |
| **$/GB-hr** | Market index ÷ memory GB |

### Coverage changes

Adding or losing a provider changes the index **level** without any price moving. Two
safeguards keep that from being read as a market move:

1. **Matched-provider changes.** 7- and 30-day changes compare the two dates using only
   providers listed on both, so a new provider can't create a fake jump and a departing
   one can't create a fake drop.
2. **Coverage markers.** Every date on which providers join or leave is published in
   `coverage_changes` and marked on the dashboard's history chart. For example, CoreWeave,
   Nebius, Crusoe and Hyperstack joined with methodology 1.1.

Published prices are rounded half-up to the cent, and percentages to the whole percent,
so the dashboard, CSV exports, brief and MCP server all show identical figures.

### Cluster cost estimates

The calculator and the MCP tool quote `gpu_count × hours × provider's cheapest listed
per-GPU price` for each provider, plus the same quantity at the market index. These are
list-price budget checks, not quotes. They exclude storage, networking, egress and the
committed-use discounts that large buyers typically negotiate.

### Build vs rent

The build-vs-rent calculator (`src/gpu_index/tco.py`, mirrored in `site/tco.js`) compares
the monthly cost of owning 8-GPU servers with renting on demand at today's index:

| Component | Formula (per server, per month) |
|---|---|
| Depreciation | capex ÷ (years × 12), straight line, no residual value |
| Cost of capital | capex × rate ÷ 2 ÷ 12 (interest on the average balance) |
| Colocation | server kW × $/kW-month (space, cooling, power delivery) |
| Operations | capex × ops % ÷ 12 (support, spares, network, staff) |
| Energy | server kW × (idle + (1 − idle) × utilization) × PUE × 730 h × $/kWh |

Renting costs `rate × GPUs × 730 h × utilization`, because on-demand capacity is paid
only while used. **Breakeven utilization** is where the two are equal per useful GPU-hour.
**Payback** is the first month in which cumulative ownership cash cost (capex up front,
then monthly costs) falls below cumulative rent. Defaults are 5-year depreciation, 8%
cost of capital, PUE 1.3, $0.08/kWh, $150/kW-month colocation, 8%/yr operations and a
35% idle power draw. Server power uses vendor reference-system maximums (DGX H100
10.2 kW, DGX B200 14.3 kW, DGX A100 6.5 kW). **Server prices are illustrative round
numbers, not market data.** Every assumption can be edited on the dashboard and through
the MCP tool.

## 4. Quality gates

Every source is screened *before* anything is stored (`src/gpu_index/validate.py`):

| Check | Severity | Rule |
|---|---|---|
| Schema | error, row dropped | Known GPU key, valid segment/pricing, `gpu_count ≥ 1` |
| Bounds | error, row dropped | $0.05 ≤ price ≤ $100 per GPU-hour |
| Volume | error, source rejected | Fewer valid rows than the source's minimum (a silent upstream format change shows up here). None of its rows are written |
| Source failure | error, source rejected | Fetch or parse raised. Other sources still run |
| Drift | warning | A provider's median for a GPU moves more than 40% day over day |
| Missing provider | warning | A provider listed yesterday is absent today |

A rejected source never overwrites good data: earlier same-day rows are kept.

### Outages

If a provider is missing *entirely* on a day, which means its source failed, its last
observed prices are **carried forward for up to 3 days** and flagged in the snapshot
(`carried_forward`) and on the dashboard. Without this, an Azure outage would drop the
A100 80GB index from $2.19 to $1.59 overnight, a fake −27% "move". A provider that's
present but stops listing one GPU is treated as a real delisting and is not carried forward.
After 3 days without data, the provider drops out of the index.

Errors fail the workflow, which opens (or comments on) a `pipeline-failure` issue. The next
healthy run closes it. Warnings are published on the dashboard's pipeline panel, because
real prices do sometimes move sharply.

## 5. Limitations

- **List prices aren't transaction prices.** Large buyers rarely pay on-demand list. The index
  measures the published price surface, which is the anchor for those negotiations, not the
  discount off it.
- **Coverage is deliberately limited to clean sources.** Nine sources and ten providers,
  each publishing prices publicly with terms that allow automated reads. Google Cloud and
  Oracle Cloud are not yet included, so the hyperscaler segment is AWS and Azure.
- **Marketplace medians depend on supply.** A GPU with a handful of listings can swing on one
  host's price. `sample_size` is published for every marketplace observation.
- **Peak FLOPS aren't throughput.** Price-performance uses vendor peaks. Delivered
  performance varies with workload, interconnect and software.
- **History starts 2026-09-29.** Trend figures stay blank until enough history exists. No
  history is back-filled or estimated.

## 6. Changes

The methodology version is published in every snapshot (`methodology_version`). Changes
that alter published values bump the version and are listed here.

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-09-29 | Initial methodology |
| 1.1 | 2026-10-04 | Added CoreWeave, Nebius, Crusoe and Hyperstack (neocloud segment from 2 to 6 providers); changes now matched-provider; coverage changes published; spot series includes neocloud spot |
