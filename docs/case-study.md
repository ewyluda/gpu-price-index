# Case study: GPU Price Index

*An open, daily index of GPU rental prices, built by directing AI agents and shipped with
AI inside the product.* · [Live dashboard](https://ewyluda.github.io/gpu-price-index/) ·
[Code](https://github.com/ewyluda/gpu-price-index) · [Methodology](methodology.md)

**In short**

- I turned a broken prototype that had never stored a single price into a daily index of
  **~600 prices from 12 providers**, collected in about 14 seconds. Every run since launch
  has passed its quality gates.
- The work was AI-native in two ways. **I directed coding agents to build it**, with a
  separate agent reviewing their work. And **AI runs inside the product**: a Claude-written
  daily brief that can't publish a number it didn't get from the data, at about $0.03 a
  day, plus an MCP server that lets any agent price out a GPU cluster.
- The decisions that made it trustworthy were judgment calls, not code. I dropped a data
  source over its terms. I kept outages and coverage changes from passing as price moves.
  And I chose not to filter real volatility that looked like an error.

## The problem

In data-center delivery, a lot of decisions eventually hinge on one number: what an hour of
GPU compute is worth. It shapes build-vs-rent calls, capacity plans and how much a cluster
is worth to a customer. Yet the public answer is fragmented across dozens of price pages,
and the published benchmarks are proprietary.

The spread is large enough to matter. On the index's first day, an H100 listed at a
**$3.82/GPU-hr** market median. The hyperscaler median was **$12.12**, and marketplace
offers started at **$2.69**. That's a 4.5× spread for the same silicon, depending mostly
on where you rent it.

## Where it started

The project began as a Selenium scraper for a single third-party index. Before adding
anything, I had an agent audit it. The audit found three problems:

1. **It had never worked.** The database held zero prices. The parser targeted
   auto-generated element IDs that weren't on the page.
2. **The browser wasn't needed.** The data sat in the plain HTTP response the whole time,
   and each run spent about 100 seconds driving headless Chrome to get nothing.
3. **The source was off-limits.** The publisher's terms prohibit storing or redistributing
   its data, which rules it out for a public project.

The third finding decided the direction: rebuild from the providers' own public price
lists, so every number traces to whoever set the price.

## What I built

- **A daily pipeline.** Adapters for eleven public sources normalize every price to USD per
  GPU-hour. They cover all four hyperscalers (AWS, Azure, Google Cloud, Oracle), five
  neoclouds (CoreWeave, Nebius, Crusoe, Lambda, Hyperstack), and RunPod and Vast.ai. Validation gates check each source before
  anything is stored. A GitHub Actions job commits each day's prices to the repo as CSV and
  redeploys the dashboard. If a source breaks, the job opens a GitHub issue, and the next
  healthy run closes it.
- **An index methodology** for 11 data-center GPUs, split into hyperscaler, neocloud and
  marketplace segments, with price-performance ($ per PFLOP-hour) and regional views.
- **Decision tools.** A cluster cost calculator ("512 H100s for 90 days, quoted per
  provider") and a **build-vs-rent model** comparing the full cost of owning 8-GPU servers
  with renting at the index. With the default assumptions, 64 H100s at 70% utilization
  cost $2.16 per useful GPU-hour to own against $4.02 to rent. Owning breaks even at 37%
  utilization and pays back in month 22. (The hardware price defaults are placeholders;
  every assumption is editable.)
- **A static dashboard** with no build step and no dependencies, with light and dark
  themes, keyboard-accessible charts, and a table view for every chart.

## The decisions that mattered

Most of the value was in a handful of calls about what the numbers should mean.

**1. Primary sources only, checked before admission.** Dropping the original source was
the easy part. The harder part was making the rule repeatable. A new source is added only
after a robots.txt and terms check, and the reason is recorded in the code. Two candidates
failed: Together AI (its robots.txt disallows all crawlers) and Verda (its terms list
scrapers among prohibited uses). Both are documented as excluded rather than quietly
skipped.

**2. One vote per provider.** Azure lists hundreds of regional prices, and Lambda lists
one. Averaging every row would mostly measure Azure. The index takes each provider's median
first, then the median across providers.

**3. Outages must not look like price moves.** A code review found that if Azure's feed
failed for a day, the A100 index would drop 27% and MI300X 39%, and the dashboard and
brief would report it as a market move. Now a missing provider's last prices are carried
forward for up to three days, flagged on the dashboard, and a warning is raised.

**4. Coverage changes aren't price changes either.** Adding four neoclouds raised the
MI300X index from $2.39 to $2.92 without a single price changing. Week-over-week changes
are now computed only over providers present on both dates, and days when providers join
or leave are marked on the history chart.

**5. Filter noise, not news.** A marketplace median from three listings is one host's
asking price. B200 launched at three Vast.ai listings, about 20% above every later day.
Models now need at least five listings to count. But when the Vast.ai H100 median later
jumped 58% across 22 listings, I left it in: that was a real market move. It's flagged as
a warning, not filtered.

## Applied AI, two ways

### Inside the product

**The daily brief.** Claude writes a short market summary from a pre-rounded fact sheet.
The model is allowed to write prose, but not numbers. Every dollar figure, signed
percentage, multiple and bare number in its draft is checked against the facts for the GPU
that sentence names. The tests cover the ways a model slips:
- a flipped or missing sign
- "9.99 dollars" instead of "$9.99"
- "7X" in place of "7x"
- a real number attributed to the wrong GPU

A draft that fails gets one retry with feedback, then the brief falls back to a
deterministic template. Each brief records its token usage and cost: about **$0.03 a day,
under $1 a month**.

**The MCP server.** The same data and cost logic are exposed as tools any agent can call.
An agent can answer "what would 512 H100s for a quarter cost at neoclouds vs hyperscalers,
and at what utilization should we buy instead?" from live data, with the same results the
dashboard shows.

### In the build

I built this by directing Claude Code agents, the way I'd run a delivery program: set the
scope, make or approve each decision, review the output, and hold every phase to acceptance
criteria before merging. The agents did the audit, the implementation, the tests and the
docs.

Three practices made that work:

- **A separate agent reviews before launch.** An independent review pass found seven
  correctness issues the building agent had missed, including the outage problem above. All
  seven were fixed with regression tests before merging.
- **Show it running, not just passing tests.** Every source was run against the live site
  before merging. The model's API request was checked against the real endpoint. The MCP
  server was exercised over a real client connection. The dashboard was checked in a
  browser at desktop and phone widths.
- **Guardrails that don't depend on trust.** Every change carries its own tests: recorded
  fixtures, strict typing, and a check that the JavaScript build-vs-rent math matches the
  Python reference. Every change goes through CI and a pull request. Agent-written commits
  carry a `Co-Authored-By` trailer, so the history shows who wrote what.

## Results

| | Prototype | GPU Price Index |
|---|---|---|
| Prices stored | 0 | ~600 per day |
| Providers | 1 (third-party index) | 12, all primary sources |
| Collection run | ~100 s, headless browser | ~14 s, plain HTTP |
| Data quality | none | schema, bounds, volume and drift gates; outage carry-forward |
| Tests | print scripts, no assertions | 102 Python tests + JS/Python parity check |
| Automation | manual | daily job, self-opening and self-closing failure issues |
| AI in the product | none | fact-checked daily brief (~$0.03/day), MCP server |

<!-- TODO (around 2026-10-12): add a price-history screenshot (docs/img/) once two weeks of
data exist, plus one sentence with a real week-over-week move from the dashboard. -->

## What I'd do next

- **Cover Google Cloud in every region** through its Cloud Billing Catalog API. The keyless
  pricing page used today covers one region.
- **Add reserved and committed pricing** where providers publish it, since that's what
  large buyers actually pay.
- **Ship a weekly digest** to Slack or email that flags significant index moves.

---

*Built by Eric Wyluda. Questions, or want to talk about applied AI in data-center
delivery? [LinkedIn](https://www.linkedin.com/in/ericwyluda/).*
