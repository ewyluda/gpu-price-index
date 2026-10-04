// GPU Price Index dashboard. No build step, no dependencies: fetches the JSON the
// daily pipeline publishes to ./data and renders SVG charts by hand.

import { buildVsRent, costCurve } from "./tco.js";

const SEGMENTS = ["hyperscaler", "neocloud", "marketplace"];
const SEGMENT_LABEL = { hyperscaler: "Hyperscaler", neocloud: "Neocloud", marketplace: "Marketplace", index: "Market index" };
const HISTORY_SERIES = ["index", ...SEGMENTS];
const MODEL_LABEL = { "claude-opus-5-5": "Claude Opus 5.5", "claude-opus-4-8": "Claude Opus 4.8", "claude-sonnet-5-5": "Claude Sonnet 5.5" };
const SVG_NS = "http://www.w3.org/2000/svg";

const state = { snap: null, history: null, status: null, brief: null, gpu: "H100", metric: "pflop" };

// ---- helpers -----------------------------------------------------------------
const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const usd = (v, d = 2) => (v == null ? "–" : `$${Number(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d })}`);
const pct = (v, signed = true) => (v == null ? "–" : `${signed && v > 0 ? "+" : ""}${(v * 100).toFixed(0)}%`);
const compactUsd = (v) => {
  const abs = Math.abs(v);
  if (abs >= 1e9) return `$${(v / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `$${(v / 1e6).toFixed(2)}M`;
  if (abs >= 1e4) return `$${(v / 1e3).toFixed(1)}K`;
  return usd(v);
};
const fmtDate = (iso, opts = { month: "short", day: "numeric", year: "numeric" }) =>
  new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-US", { timeZone: "UTC", ...opts });
const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const segColor = (seg) => `var(--s-${seg})`;

function el(tag, attrs = {}, parent) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v != null) node.setAttribute(k, v);
  if (parent) parent.appendChild(node);
  return node;
}

function svgFor(container, height) {
  const width = Math.max(container.clientWidth, 280);
  container.replaceChildren();
  const svg = el("svg", { viewBox: `0 0 ${width} ${height}`, width, height }, container);
  return { svg, width };
}

function niceMax(v) {
  const exp = 10 ** Math.floor(Math.log10(v));
  const f = v / exp;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * exp;
}

function ticks(max, count = 5) {
  const step = niceMax(max / count);
  const out = [];
  for (let t = 0; t <= max + 1e-9; t += step) out.push(+t.toFixed(6));
  return out;
}

const isNarrow = () => window.matchMedia("(max-width: 600px)").matches;
// Compact labels for narrow charts: "A100-80GB-PCIe" -> "A100 PCIe", "H100-NVL" -> "H100 NVL".
const shortName = (g) => g.key.replace("-80GB-PCIe", " PCIe").replace("-80GB", "").replace("-", " ");
const chartName = (g) => (isNarrow() ? shortName(g) : g.name);

// ---- tooltip -----------------------------------------------------------------
const tip = $("#tooltip");
function showTip(html, x, y) {
  tip.innerHTML = html;
  tip.hidden = false;
  const { width, height } = tip.getBoundingClientRect();
  const left = Math.min(Math.max(8, x + 14), window.innerWidth - width - 8);
  const top = y + height + 20 > window.innerHeight ? y - height - 14 : y + 14;
  tip.style.left = `${left}px`;
  tip.style.top = `${Math.max(8, top)}px`;
}
const hideTip = () => { tip.hidden = true; };
function bindTip(node, html) {
  node.setAttribute("tabindex", "0");
  node.addEventListener("pointermove", (e) => showTip(html(), e.clientX, e.clientY));
  node.addEventListener("pointerleave", hideTip);
  node.addEventListener("focus", () => { const r = node.getBoundingClientRect(); showTip(html(), r.left + r.width / 2, r.top + r.height / 2); });
  node.addEventListener("blur", hideTip);
}
const ttRow = (label, value, color) =>
  `<div class="tt-row"><span>${color ? `<i class="sw" style="background:${color}"></i>` : ""}${esc(label)}</span><span>${value}</span></div>`;

// ---- data --------------------------------------------------------------------
async function loadJSON(name) {
  const res = await fetch(`data/${name}`, { cache: "no-cache" });
  if (!res.ok) throw new Error(`${name}: HTTP ${res.status}`);
  return res.json();
}

const gpuByKey = (key) => state.snap.gpus.find((g) => g.key === key);
const headlineGpus = () => state.snap.gpus.filter((g) => g.headline);

// ---- header, hero, brief -------------------------------------------------------
function renderStatus() {
  const pill = $("#status-pill");
  const run = state.status?.latest;
  const okCount = run ? run.sources.filter((s) => s.ok).length : 0;
  const total = run ? run.sources.length : 0;
  pill.classList.toggle("ok", !!run?.ok);
  pill.classList.toggle("bad", !!run && !run.ok);
  pill.lastElementChild.textContent = run
    ? `${fmtDate(state.snap.as_of, { month: "short", day: "numeric" })} · ${okCount}/${total} sources`
    : `Updated ${fmtDate(state.snap.as_of)}`;
  const s = state.snap;
  $("#asof").textContent =
    `As of ${fmtDate(s.as_of)} · ${s.observations.toLocaleString()} prices from ${s.providers.length} providers · ` +
    (s.days_of_history > 1 ? `${s.days_of_history} days of history since ${fmtDate(s.first_date)}` : `history starts ${fmtDate(s.first_date)}`) +
    (s.carried_forward?.length ? ` · last known prices carried forward for ${s.carried_forward.join(", ")} (source unavailable)` : "");
}

function renderBrief() {
  const b = state.brief;
  if (!b) { $("#brief").hidden = true; return; }
  $("#brief-headline").textContent = b.headline;
  $("#brief-bullets").replaceChildren(...b.bullets.map((t) => Object.assign(document.createElement("li"), { textContent: t })));
  $("#brief-watch").textContent = b.watch;
  $("#brief-badge").textContent = b.generator === "claude" ? "Written by Claude · numbers fact-checked" : "Generated from today's data";
  const u = b.usage;
  if (u) {
    const cost = u.usd == null ? "cost unknown" : `${usd(u.usd, 3)} to write`;
    $("#brief-cost").textContent = `${cost} · ${(u.input_tokens + u.output_tokens).toLocaleString()} tokens`;
    $("#brief-cost").hidden = false;
    const mtd = u.month_to_date_usd == null ? "" : ` · ${usd(u.month_to_date_usd)} month to date`;
    $("#ai-usage").textContent =
      `${MODEL_LABEL[u.models.at(-1)] ?? u.models.at(-1)} · ${u.requests} request${u.requests === 1 ? "" : "s"} · ` +
      `${u.input_tokens.toLocaleString()} input / ${u.output_tokens.toLocaleString()} output tokens · ` +
      `${u.usd == null ? "cost unknown" : usd(u.usd, 3)}${mtd}` +
      (b.generator === "claude" ? "" : ` · fell back to template (${b.fallback_reason ?? "unknown reason"})`);
  }
}

// ---- tiles ---------------------------------------------------------------------
function renderTiles() {
  const tiles = $("#tiles");
  tiles.replaceChildren();
  for (const g of headlineGpus()) {
    const s = g.series.index;
    const provs = g.providers.map((p) => p.median);
    const lo = Math.min(...provs), hi = Math.max(...provs);
    const pos = (v) => (hi === lo ? 50 : ((v - lo) / (hi - lo)) * 100);
    const change = s.change_7d == null ? "New series" : `${pct(s.change_7d)} 7d`;
    const btn = document.createElement("button");
    btn.className = "tile";
    btn.type = "button";
    btn.setAttribute("aria-label", `${g.name}: ${usd(s.value)} per GPU-hour. Explore.`);
    btn.innerHTML = `
      <div class="tile-name"><span>${esc(g.name)}</span>${g.name.includes("GB") ? "" : `<span>${g.memory_gb} GB</span>`}</div>
      <div class="tile-value">${usd(s.value)}<small> /GPU-hr</small></div>
      <div class="tile-meta">${change} · ${s.n_providers} providers</div>
      <div class="range" title="Provider medians from ${usd(lo)} to ${usd(hi)}">
        ${g.providers.map((p) => `<i style="left:${pos(p.median)}%;background:${segColor(p.segment)}"></i>`).join("")}
      </div>
      <div class="tile-meta num">${usd(lo)} – ${usd(hi)}</div>`;
    btn.addEventListener("click", () => { selectGpu(g.key); $("#explore").scrollIntoView(); });
    tiles.appendChild(btn);
  }
}

// ---- segment ladder (dot plot) ------------------------------------------------------
function renderLadder() {
  const container = $("#ladder");
  const gpus = state.snap.gpus;
  const rowH = 34, top = 8, axisH = 28;
  const { svg, width } = svgFor(container, top + gpus.length * rowH + axisH);
  const labelW = isNarrow() ? 84 : 140, right = 16;
  const maxV = niceMax(Math.max(...gpus.flatMap((g) => SEGMENTS.map((s) => g.series[s]?.value ?? 0))));
  const x = (v) => labelW + (v / maxV) * (width - labelW - right);
  const plotBottom = top + gpus.length * rowH;

  for (const t of ticks(maxV, isNarrow() ? 4 : 6)) {
    el("line", { x1: x(t), x2: x(t), y1: top, y2: plotBottom, class: "gridline" }, svg);
    el("text", { x: x(t), y: plotBottom + 18, "text-anchor": "middle" }, svg).textContent = `$${t}`;
  }
  gpus.forEach((g, i) => {
    const cy = top + i * rowH + rowH / 2;
    const row = el("g", { class: "row" }, svg);
    const label = el("text", { x: 0, y: cy + 4, class: "label" }, row);
    label.textContent = chartName(g);
    const vals = SEGMENTS.filter((s) => g.series[s]).map((s) => [s, g.series[s].value]);
    if (vals.length > 1) {
      const xs = vals.map(([, v]) => x(v));
      el("line", { x1: Math.min(...xs), x2: Math.max(...xs), y1: cy, y2: cy, class: "connector" }, row);
    }
    for (const [seg, v] of vals) el("circle", { cx: x(v), cy, r: 6, fill: segColor(seg), class: "dot" }, row);
    const hit = el("rect", { x: 0, y: cy - rowH / 2, width, height: rowH, class: "hit", role: "img",
      "aria-label": `${g.name}: ${vals.map(([s, v]) => `${SEGMENT_LABEL[s]} ${usd(v)}`).join(", ")}` }, row);
    row.insertBefore(hit, row.firstChild);
    bindTip(hit, () => `<b>${esc(g.name)}</b>` +
      vals.map(([s, v]) => ttRow(SEGMENT_LABEL[s], usd(v), segColor(s))).join("") +
      ttRow("Market index", usd(g.series.index.value)) +
      (g.hyperscaler_premium != null ? ttRow("Hyperscaler premium", pct(g.hyperscaler_premium)) : ""));
  });

  $("#ladder-table").innerHTML = table(
    ["GPU", "Hyperscaler", "Neocloud", "Marketplace", "Index"],
    gpus.map((g) => [esc(g.name), ...[...SEGMENTS, "index"].map((s) => usd(g.series[s]?.value))]),
    [1, 2, 3, 4],
  );
}

// ---- horizontal bar chart (price-performance, premium) --------------------------
function barChart(container, rows, { format, color = "var(--bar)" }) {
  const rowH = 30, top = 4;
  const { svg, width } = svgFor(container, top + rows.length * rowH + 4);
  const labelW = isNarrow() ? 84 : 140, valueW = 64;
  const maxV = Math.max(...rows.map((r) => r.value));
  const w = (v) => Math.max(2, (v / maxV) * (width - labelW - valueW));
  rows.forEach((r, i) => {
    const y = top + i * rowH;
    const row = el("g", { class: "row" }, svg);
    const hit = el("rect", { x: 0, y, width, height: rowH, class: "hit", role: "img", "aria-label": `${r.label}: ${format(r.value)}` }, row);
    el("text", { x: 0, y: y + rowH / 2 + 4, class: "label" }, row).textContent = r.label;
    el("rect", { x: labelW, y: y + 7, width: w(r.value), height: rowH - 14, rx: 4, class: "bar", fill: color, style: `fill:${color}` }, row);
    el("text", { x: labelW + w(r.value) + 8, y: y + rowH / 2 + 4, class: "label-2" }, row).textContent = format(r.value);
    bindTip(hit, () => `<b>${esc(r.label)}</b>${r.tip}`);
  });
}

function renderPerf() {
  const pflop = state.metric === "pflop";
  const field = pflop ? "usd_per_pflop_hour" : "usd_per_gb_hour";
  $("#perf-sub").textContent = pflop
    ? "Market index per dense BF16 PFLOP-hour. Lower is better."
    : "Market index per GB of GPU memory per hour. Lower is better.";
  const rows = state.snap.gpus
    .map((g) => ({
      label: chartName(g),
      value: g[field],
      tip: ttRow("Market index", usd(g.series.index.value)) +
        ttRow(pflop ? "BF16 dense" : "Memory", pflop ? `${g.bf16_dense_tflops.toLocaleString()} TFLOPS` : `${g.memory_gb} GB`) +
        ttRow(pflop ? "$/PFLOP-hr" : "$/GB-hr", usd(g[field], pflop ? 2 : 3)),
    }))
    .sort((a, b) => a.value - b.value);
  barChart($("#perf"), rows, { format: (v) => usd(v, pflop ? 2 : 3) });
}

function renderPremium() {
  const rows = state.snap.gpus
    .filter((g) => g.hyperscaler_premium != null)
    .map((g) => ({
      label: chartName(g),
      value: g.hyperscaler_premium,
      tip: ttRow("Hyperscaler", usd(g.series.hyperscaler.value), segColor("hyperscaler")) +
        ttRow("Neocloud", usd(g.series.neocloud.value), segColor("neocloud")) +
        ttRow("Premium", pct(g.hyperscaler_premium)),
    }))
    .sort((a, b) => b.value - a.value);
  barChart($("#premium"), rows, { format: (v) => pct(v), color: "var(--s-hyperscaler)" });
}

// ---- explore: picker, history, providers, regional ---------------------------------
function renderPicker() {
  const picker = $("#gpu-picker");
  picker.replaceChildren(
    ...state.snap.gpus.map((g) => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "chip";
      chip.setAttribute("role", "radio");
      chip.setAttribute("aria-checked", String(g.key === state.gpu));
      chip.textContent = g.name;
      chip.addEventListener("click", () => selectGpu(g.key));
      return chip;
    }),
  );
}

function selectGpu(key) {
  state.gpu = key;
  try { localStorage.setItem("gpu", key); } catch (_) {}
  renderPicker();
  renderHistory();
  renderProviders();
  renderRegional();
  const calc = $("#calc-gpu");
  if (calc.value !== key) { calc.value = key; renderCalc(); }
}

function renderHistory() {
  const g = gpuByKey(state.gpu);
  const { dates, series } = state.history;
  const data = series[state.gpu];
  const active = HISTORY_SERIES.filter((s) => data[s].some((v) => v != null));
  const container = $("#history");
  const height = isNarrow() ? 240 : 300;
  const { svg, width } = svgFor(container, height);
  const left = 44, right = isNarrow() ? 16 : 136, top = 12, bottom = 28;
  const values = active.flatMap((s) => data[s].filter((v) => v != null));
  const maxV = niceMax(Math.max(...values) * 1.08);
  const n = dates.length;
  const x = (i) => (n === 1 ? (left + width - right) / 2 : left + (i / (n - 1)) * (width - left - right));
  const y = (v) => top + (1 - v / maxV) * (height - top - bottom);

  $("#history-title").textContent = `${g.name} price history`;
  $("#history-sub").textContent = n < 7
    ? `USD per GPU-hour. The series started ${fmtDate(dates[0])}; the daily job adds a point every morning, so trend lines fill in over the coming weeks.`
    : `USD per GPU-hour, ${fmtDate(dates[0])} – ${fmtDate(dates[n - 1])}.`;
  $("#history-legend").innerHTML = active
    .map((s) => `<span><i class="sw ${n > 1 ? "sw-line" : ""} sw-${s}"></i>${SEGMENT_LABEL[s]}</span>`).join("");

  for (const t of ticks(maxV, 4)) {
    el("line", { x1: left, x2: width - right, y1: y(t), y2: y(t), class: "gridline" }, svg);
    el("text", { x: left - 8, y: y(t) + 4, "text-anchor": "end" }, svg).textContent = `$${t}`;
  }
  const tickEvery = Math.max(1, Math.ceil(n / (isNarrow() ? 4 : 7)));
  dates.forEach((d, i) => {
    if (i % tickEvery === 0 || i === n - 1)
      el("text", { x: x(i), y: height - 8, "text-anchor": "middle" }, svg).textContent = fmtDate(d, { month: "short", day: "numeric" });
  });

  const ends = [];
  for (const s of active) {
    const color = s === "index" ? "var(--s-index)" : segColor(s);
    const pts = data[s].map((v, i) => (v == null ? null : [x(i), y(v)]));
    let d = "";
    pts.forEach((p, i) => { if (p) d += `${d && pts[i - 1] ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`; });
    if (n > 1) el("path", { d, class: "line", stroke: color, style: `stroke:${color}` }, svg);
    const lastIdx = data[s].findLastIndex((v) => v != null);
    el("circle", { cx: pts[lastIdx][0], cy: pts[lastIdx][1], r: 4.5, fill: color, class: "dot", style: `fill:${color}` }, svg);
    ends.push({ s, y: pts[lastIdx][1], x: pts[lastIdx][0], v: data[s][lastIdx] });
  }
  // Direct end labels, nudged apart so they never overlap.
  if (!isNarrow()) {
    ends.sort((a, b) => a.y - b.y);
    for (let i = 1; i < ends.length; i++) ends[i].y = Math.max(ends[i].y, ends[i - 1].y + 15);
    for (const e of ends) {
      el("text", { x: e.x + 10, y: e.y + 4, class: e.s === "index" ? "label" : "label-2" }, svg).textContent =
        `${usd(e.v)} ${e.s === "index" ? "Index" : SEGMENT_LABEL[e.s]}`;
    }
  }

  // Crosshair + tooltip on the nearest date.
  const cross = el("line", { y1: top, y2: height - bottom, class: "crosshair", visibility: "hidden" }, svg);
  const overlay = el("rect", { x: left, y: top, width: width - left - right, height: height - top - bottom, class: "hit", role: "img",
    "aria-label": `${g.name} price history; table view below` }, svg);
  const nearest = (clientX) => {
    const box = svg.getBoundingClientRect();
    const px = ((clientX - box.left) / box.width) * width;
    return n === 1 ? 0 : Math.round(Math.min(Math.max((px - left) / (width - left - right), 0), 1) * (n - 1));
  };
  const tipFor = (i) => `<b>${fmtDate(dates[i])}</b>` +
    active.map((s) => ttRow(SEGMENT_LABEL[s], usd(data[s][i]), s === "index" ? "var(--s-index)" : segColor(s))).join("");
  overlay.addEventListener("pointermove", (e) => {
    const i = nearest(e.clientX);
    cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("visibility", "visible");
    showTip(tipFor(i), e.clientX, e.clientY);
  });
  overlay.addEventListener("pointerleave", () => { cross.setAttribute("visibility", "hidden"); hideTip(); });

  const recent = dates.map((d, i) => i).slice(-60).reverse();
  $("#history-table").innerHTML = table(
    ["Date", ...active.map((s) => SEGMENT_LABEL[s])],
    recent.map((i) => [dates[i], ...active.map((s) => usd(data[s][i]))]),
    active.map((_, i) => i + 1),
  );
}

function table(headers, rows, rightCols = []) {
  const cls = (i) => (rightCols.includes(i) ? ' class="r"' : "");
  return `<div class="table-wrap"><table><thead><tr>${headers.map((h, i) => `<th${cls(i)}>${esc(h)}</th>`).join("")}</tr></thead>
    <tbody>${rows.map((r) => `<tr>${r.map((c, i) => `<td${cls(i)}>${c}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}

const segTag = (seg) => `<span class="seg-tag"><i class="sw sw-${seg}"></i>${SEGMENT_LABEL[seg]}</span>`;

function renderProviders() {
  const g = gpuByKey(state.gpu);
  $("#providers").innerHTML = table(
    ["Provider", "Median", "Cheapest", "Regions"],
    g.providers.map((p) => [
      `<div class="prov"><strong>${esc(p.provider)}</strong>${segTag(p.segment)}</div>` +
        `<div class="mono wrap-any">${esc(p.best_sku)}${p.best_region !== "global" ? ` · ${esc(p.best_region)}` : ""}` +
        `${p.best_sku === "median-offer" ? ` · median of ${p.sample_size} offers` : ""}</div>`,
      usd(p.median),
      usd(p.min),
      p.n_regions,
    ]),
    [1, 2, 3],
  ).replace('<div class="table-wrap">', "<div>");
}

function renderRegional() {
  const g = gpuByKey(state.gpu);
  const GEO = { NA: "North America", EU: "Europe", APAC: "Asia-Pacific", ME: "Middle East", LATAM: "Latin America", AF: "Africa" };
  const order = Object.keys(GEO);
  const geos = Object.keys(g.regional).sort((a, b) => order.indexOf(a) - order.indexOf(b));
  $("#regional").innerHTML = geos.length
    ? table(
        ["Region", ...SEGMENTS.filter((s) => geos.some((geo) => g.regional[geo][s] != null)).map((s) => SEGMENT_LABEL[s])],
        geos.map((geo) => [GEO[geo] ?? geo, ...SEGMENTS.filter((s) => geos.some((x) => g.regional[x][s] != null)).map((s) => usd(g.regional[geo][s]))]),
        [1, 2, 3],
      ).replace('<div class="table-wrap">', "<div>")
    : `<p class="muted">No region-specific list prices for ${esc(g.name)} today; every provider lists it globally.</p>`;
}

// ---- calculator -----------------------------------------------------------------
function renderCalc() {
  const g = gpuByKey($("#calc-gpu").value);
  const count = Math.max(1, Math.floor(+$("#calc-count").value || 1));
  const hours = Math.max(1, +$("#calc-duration").value || 1) * +$("#calc-unit").value;
  const segment = $("#calc-segment").value;
  const gpuHours = count * hours;
  const indexTotal = g.series.index.value * gpuHours;
  $("#calc-total").textContent = compactUsd(indexTotal);
  $("#calc-detail").textContent =
    `${count.toLocaleString()} × ${g.name} for ${hours.toLocaleString()} hours = ${gpuHours.toLocaleString()} GPU-hours at ${usd(g.series.index.value)}/GPU-hr`;
  const quotes = g.providers
    .filter((p) => !segment || p.segment === segment)
    .map((p) => ({ ...p, total: p.min * gpuHours }))
    .sort((a, b) => a.total - b.total);
  const max = Math.max(...quotes.map((q) => q.total), 1);
  $("#calc-quotes").innerHTML = quotes.length
    ? quotes.map((q) => `
      <div class="quote">
        <div><strong>${esc(q.provider)}</strong> <span class="q-meta">${SEGMENT_LABEL[q.segment]} · ${usd(q.min)}/GPU-hr · <span class="mono">${esc(q.best_sku)}</span></span></div>
        <div class="q-total">${compactUsd(q.total)}</div>
        <div class="q-bar"><i style="width:${(q.total / max) * 100}%;background:${segColor(q.segment)}"></i></div>
      </div>`).join("")
    : `<p class="muted" style="margin-top:12px">No ${SEGMENT_LABEL[segment].toLowerCase()} provider lists ${esc(g.name)} today.</p>`;
}

function initCalc() {
  const select = $("#calc-gpu");
  select.replaceChildren(...state.snap.gpus.map((g) => new Option(g.name, g.key)));
  select.value = state.gpu;
  $("#calc-form").addEventListener("input", renderCalc);
  $("#calc-form").addEventListener("submit", (e) => e.preventDefault());
  renderCalc();
}

// ---- build vs rent ---------------------------------------------------------------
const own = { gpu: "H100", assumptions: null };
const ownInputs = () => [...document.querySelectorAll("#own-form [data-key]")];
const rentColor = (seg) => (seg === "index" ? "var(--muted)" : segColor(seg));
const rentLabel = (seg) => (seg === "index" ? "Rent (market index)" : `Rent (${SEGMENT_LABEL[seg].toLowerCase()})`);

function loadOwnDefaults() {
  own.assumptions = { ...gpuByKey(own.gpu).own_defaults };
  for (const input of ownInputs()) {
    const v = own.assumptions[input.dataset.key];
    input.value = input.dataset.pct !== undefined ? +(v * 100).toFixed(2) : v;
  }
}

function readOwnAssumptions() {
  for (const input of ownInputs()) {
    const v = parseFloat(input.value);
    if (Number.isFinite(v) && v >= 0) own.assumptions[input.dataset.key] = input.dataset.pct !== undefined ? v / 100 : v;
  }
  if (own.assumptions.depreciation_years < 1) own.assumptions.depreciation_years = 1;
}

function renderOwn() {
  const g = gpuByKey(own.gpu);
  const segment = $("#own-segment").value;
  const util = +$("#own-util").value / 100;
  const count = Math.max(1, Math.floor(+$("#own-count").value || 1));
  $("#own-util-out").textContent = `${Math.round(util * 100)}%`;
  const rate = g.series[segment]?.value;
  if (!rate) {
    $("#own-tiles").replaceChildren();
    $("#own-verdict").textContent = `No ${SEGMENT_LABEL[segment].toLowerCase()} price for ${g.name} today. Pick another rental benchmark.`;
    for (const id of ["#own-curve", "#own-cum", "#own-breakdown"]) $(id).replaceChildren();
    return;
  }
  const r = buildVsRent(own.assumptions, count, util, rate);
  const be = r.breakeven_utilization;
  const tile = (label, value, note) => `<div class="own-tile"><span>${label}</span><strong>${value}</strong><small>${note}</small></div>`;
  $("#own-tiles").innerHTML =
    tile("Own", usd(r.own_usd_per_gpu_hour), `per useful GPU-hr at ${Math.round(util * 100)}%`) +
    tile("Rent", usd(rate), `per GPU-hr, ${segment === "index" ? "market index" : SEGMENT_LABEL[segment].toLowerCase() + " median"}`) +
    tile("Breakeven", be == null ? "None" : `${Math.round(be * 100)}%`, be == null ? "renting wins at any utilization" : "utilization where owning wins") +
    tile("Payback", r.payback_month == null ? "None" : `${r.payback_month} mo`, `within a ${r.horizon_months}-month horizon`);
  const cheaper = r.own_usd_per_gpu_hour < rate;
  const diff = Math.abs(r.horizon_savings_usd);
  $("#own-verdict").textContent = be == null
    ? `Renting is cheaper: even at 100% utilization, owning ${g.name}s costs more than ${usd(rate)}/GPU-hr.`
    : cheaper
      ? `At ${Math.round(util * 100)}% utilization, owning is cheaper and saves about ${compactUsd(diff)} over ${r.horizon_months / 12} years. It stops paying off below ${Math.round(be * 100)}%.`
      : `At ${Math.round(util * 100)}% utilization, renting is cheaper. Owning only pays off above ${Math.round(be * 100)}% utilization.`;

  $("#own-legend").innerHTML =
    `<span><i class="sw sw-line" style="background:var(--s-index)"></i>Own</span>` +
    `<span><i class="sw sw-line" style="background:${rentColor(segment)}"></i>${rentLabel(segment)}</span>`;
  renderOwnCurve(r, count, rate, segment, util);
  renderOwnCumulative(r, segment);

  const b = r.own_monthly_breakdown_usd;
  const label = { depreciation: "Depreciation", capital: "Cost of capital", colocation: "Colocation", operations: "Operations", energy: "Energy" };
  $("#own-breakdown").innerHTML = table(
    ["Monthly cost", "USD", "Share"],
    [...Object.entries(b).map(([k, v]) => [label[k], usd(v, 0), `${Math.round((v / r.own_monthly_usd) * 100)}%`]),
     ["<strong>Own, total</strong>", `<strong>${usd(r.own_monthly_usd, 0)}</strong>`, ""],
     [`Rent at ${Math.round(util * 100)}% utilization`, usd(r.rent_monthly_usd, 0), ""]],
    [1, 2],
  );
}

let clipSeq = 0;
function lineChart(container, { xs, series, xTicks, xFmt, yFmt, yMax, markers = [], tipFor, height = 240 }) {
  const { svg, width } = svgFor(container, height);
  const left = 54, right = 16, top = 10, bottom = 28;
  const x = (v) => left + ((v - xs[0]) / (xs[xs.length - 1] - xs[0])) * (width - left - right);
  const y = (v) => top + (1 - v / yMax) * (height - top - bottom);
  const clipId = `clip-${++clipSeq}`;
  const clip = el("clipPath", { id: clipId }, el("defs", {}, svg));
  el("rect", { x: left, y: top - 6, width: width - left - right + 6, height: height - top - bottom + 6 }, clip);
  for (const t of ticks(yMax, 4)) {
    el("line", { x1: left, x2: width - right, y1: y(t), y2: y(t), class: "gridline" }, svg);
    el("text", { x: left - 8, y: y(t) + 4, "text-anchor": "end" }, svg).textContent = yFmt(t);
  }
  for (const v of xTicks) el("text", { x: x(v), y: height - 8, "text-anchor": "middle" }, svg).textContent = xFmt(v);
  for (const m of markers) {
    el("line", { x1: x(m.x), x2: x(m.x), y1: top, y2: height - bottom, class: "marker" }, svg);
    el("text", { x: x(m.x) + 6, y: top + 12, class: "label-2" }, svg).textContent = m.label;
  }
  for (const s of series) {
    const d = s.values.map((v, i) => `${i ? "L" : "M"}${x(xs[i]).toFixed(1)},${y(v).toFixed(1)}`).join("");
    el("path", { d, class: "line", style: `stroke:${s.color}`, "clip-path": `url(#${clipId})` }, svg);
    for (const p of s.points ?? []) if (p[1] <= yMax) el("circle", { cx: x(p[0]), cy: y(p[1]), r: 5, class: "dot", style: `fill:${s.color}` }, svg);
  }
  const cross = el("line", { y1: top, y2: height - bottom, class: "crosshair", visibility: "hidden" }, svg);
  const overlay = el("rect", { x: left, y: top, width: width - left - right, height: height - top - bottom, class: "hit" }, svg);
  overlay.addEventListener("pointermove", (e) => {
    const box = svg.getBoundingClientRect();
    const px = ((e.clientX - box.left) / box.width) * width;
    const i = Math.round(Math.min(Math.max((px - left) / (width - left - right), 0), 1) * (xs.length - 1));
    cross.setAttribute("x1", x(xs[i])); cross.setAttribute("x2", x(xs[i])); cross.setAttribute("visibility", "visible");
    showTip(tipFor(i), e.clientX, e.clientY);
  });
  overlay.addEventListener("pointerleave", () => { cross.setAttribute("visibility", "hidden"); hideTip(); });
}

function renderOwnCurve(r, count, rate, segment, util) {
  const curve = costCurve(own.assumptions, count, rate);
  const xs = curve.map(([u]) => u);
  const ownVals = curve.map(([, c]) => c);
  const yMax = niceMax(Math.max(rate * 2.2, ownVals[ownVals.length - 1] * 1.6));
  const markers = r.breakeven_utilization == null ? [] : [{ x: r.breakeven_utilization, label: `Breakeven ${Math.round(r.breakeven_utilization * 100)}%` }];
  lineChart($("#own-curve"), {
    xs, yMax, markers,
    series: [
      { values: xs.map(() => rate), color: rentColor(segment) },
      { values: ownVals, color: "var(--s-index)", points: [[util, r.own_usd_per_gpu_hour]] },
    ],
    xTicks: isNarrow() ? [0.25, 0.5, 0.75, 1] : [0.1, 0.25, 0.5, 0.75, 1],
    xFmt: (u) => `${Math.round(u * 100)}%`,
    yFmt: (v) => `$${v}`,
    tipFor: (i) => `<b>${Math.round(xs[i] * 100)}% utilization</b>${ttRow("Own", usd(ownVals[i]), "var(--s-index)")}${ttRow("Rent", usd(rate), rentColor(segment))}`,
  });
}

function renderOwnCumulative(r, segment) {
  const months = r.own_cumulative_usd.map((_, m) => m);
  $("#own-cum-sub").textContent = r.payback_month == null
    ? `Over ${r.horizon_months} months, owning never catches up with renting.`
    : `Owning pays back in month ${r.payback_month} of ${r.horizon_months}.`;
  const yMax = niceMax(Math.max(r.own_cumulative_usd.at(-1), r.rent_cumulative_usd.at(-1)) * 1.05);
  lineChart($("#own-cum"), {
    xs: months, yMax,
    markers: r.payback_month == null ? [] : [{ x: r.payback_month, label: `Payback, month ${r.payback_month}` }],
    series: [
      { values: r.rent_cumulative_usd, color: rentColor(segment) },
      { values: r.own_cumulative_usd, color: "var(--s-index)" },
    ],
    xTicks: months.filter((m) => m % 12 === 0),
    xFmt: (m) => (m === 0 ? "Start" : `Year ${m / 12}`),
    yFmt: (v) => compactUsd(v).replace(".00", ""),
    tipFor: (i) => `<b>Month ${i}</b>${ttRow("Own", compactUsd(r.own_cumulative_usd[i]), "var(--s-index)")}${ttRow("Rent", compactUsd(r.rent_cumulative_usd[i]), rentColor(segment))}`,
  });
}

function initOwn() {
  const options = state.snap.gpus.filter((g) => g.own_defaults);
  if (!options.length) { $("#own").hidden = true; return; }
  const select = $("#own-gpu");
  select.replaceChildren(...options.map((g) => new Option(g.name, g.key)));
  if (!gpuByKey(own.gpu)?.own_defaults) own.gpu = options[0].key;
  select.value = own.gpu;
  loadOwnDefaults();
  select.addEventListener("change", () => { own.gpu = select.value; loadOwnDefaults(); renderOwn(); });
  $("#own-reset").addEventListener("click", () => { loadOwnDefaults(); renderOwn(); });
  $("#own-form").addEventListener("input", (e) => {
    if (e.target.dataset.key) readOwnAssumptions();
    if (e.target !== select) renderOwn();
  });
  $("#own-form").addEventListener("submit", (e) => e.preventDefault());
  renderOwn();
}

// ---- pipeline ------------------------------------------------------------------
const OK_ICON = '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="7" fill="currentColor"/><path d="M4.5 8.2l2.2 2.2 4.8-4.8" stroke="#fff" stroke-width="1.8" fill="none"/></svg>';
const BAD_ICON = '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="7" fill="currentColor"/><path d="M5.5 5.5l5 5m0-5l-5 5" stroke="#fff" stroke-width="1.8"/></svg>';

function renderPipeline() {
  const run = state.status?.latest;
  if (!run) { $("#run-sub").textContent = "No runs recorded yet."; return; }
  const when = new Date(run.collected_at);
  $("#run-sub").textContent = `${when.toUTCString().replace(" GMT", " UTC")} · ${run.observations.toLocaleString()} observations`;
  const byId = Object.fromEntries(state.snap.sources.map((s) => [s.id, s]));
  $("#sources").innerHTML = table(
    ["Source", "Status", "Rows", "Time"],
    run.sources.map((s) => [
      byId[s.id] ? `<a href="${esc(byId[s.id].homepage)}">${esc(s.name)}</a>` : esc(s.name),
      s.ok ? `<span class="status ok">${OK_ICON}OK</span>` : `<span class="status bad" title="${esc(s.error)}">${BAD_ICON}Failed</span>`,
      s.rows.toLocaleString(),
      `${s.seconds.toFixed(1)}s`,
    ]),
    [2, 3],
  ).replace('<div class="table-wrap">', "<div>");
  const notes = [
    ...(state.snap.carried_forward ?? []).map((p) => `<li><strong>Carried forward:</strong> ${esc(p)} was unavailable; its last prices are used for up to 3 days.</li>`),
    ...run.validation.errors.map((m) => `<li><strong>Error:</strong> ${esc(m)}</li>`),
    ...run.validation.warnings.map((m) => `<li><strong>Warning:</strong> ${esc(m)}</li>`),
  ];
  $("#validation").innerHTML = notes.length
    ? `<ul class="notes">${notes.join("")}</ul>`
    : `<ul class="notes"><li><strong>All validation checks passed</strong>: schema, price bounds, per-source volume, and day-over-day drift.</li></ul>`;

  const runs = $("#runs");
  runs.replaceChildren();
  for (const r of state.status.recent) {
    const sq = document.createElement("i");
    if (!r.ok) sq.className = "bad";
    sq.setAttribute("aria-label", `${r.date}: ${r.ok ? "OK" : "failed"}, ${r.observations} observations`);
    sq.setAttribute("role", "img");
    bindTip(sq, () => `<b>${fmtDate(r.date)}</b>${ttRow("Status", r.ok ? "OK" : "Failed")}${ttRow("Observations", r.observations.toLocaleString())}`);
    runs.appendChild(sq);
  }

  $("#source-links").innerHTML = state.snap.sources.map((s) => `<li><a href="${esc(s.homepage)}">${esc(s.name)}</a></li>`).join("");
}

// ---- boot ----------------------------------------------------------------------
function renderCharts() {
  renderLadder();
  renderPerf();
  renderPremium();
  renderHistory();
  if (own.assumptions) renderOwn();
}

function initControls() {
  $("#theme-toggle").addEventListener("click", () => {
    const dark = document.documentElement.dataset.theme
      ? document.documentElement.dataset.theme === "dark"
      : window.matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("theme", document.documentElement.dataset.theme); } catch (_) {}
  });
  document.querySelectorAll("[data-metric]").forEach((btn) =>
    btn.addEventListener("click", () => {
      state.metric = btn.dataset.metric;
      document.querySelectorAll("[data-metric]").forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
      renderPerf();
    }),
  );
  let lastWidth = window.innerWidth;
  new ResizeObserver(() => {
    if (Math.abs(window.innerWidth - lastWidth) < 4) return;
    lastWidth = window.innerWidth;
    renderCharts();
  }).observe(document.body);
  window.addEventListener("scroll", hideTip, { passive: true });
}

async function main() {
  document.body.classList.add("loading");
  try {
    const [snap, history, status, brief] = await Promise.all([
      loadJSON("latest.json"),
      loadJSON("history.json"),
      loadJSON("status.json").catch(() => null),
      loadJSON("brief.json").catch(() => null),
    ]);
    Object.assign(state, { snap, history, status, brief });
  } catch (err) {
    $("#asof").textContent = `Could not load data (${err.message}). If you opened this file directly, serve the folder over HTTP instead.`;
    return;
  }
  try {
    const saved = localStorage.getItem("gpu");
    if (saved && gpuByKey(saved)) state.gpu = saved;
  } catch (_) {}
  if (!gpuByKey(state.gpu)) state.gpu = state.snap.gpus[0].key;

  renderStatus();
  renderBrief();
  renderTiles();
  renderPicker();
  renderProviders();
  renderRegional();
  initCalc();
  initOwn();
  renderPipeline();
  renderCharts();
  initControls();
  document.body.classList.remove("loading");
}

main();
