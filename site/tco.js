// Build vs rent: JavaScript twin of src/gpu_index/tco.py. Keep the formulas in sync;
// both implementations are checked against tests/fixtures/tco_cases.json.

export const HOURS_PER_MONTH = 730;
export const GPUS_PER_SERVER = 8;

export const BASE_ASSUMPTIONS = {
  depreciation_years: 5,
  cost_of_capital: 0.08,
  pue: 1.3,
  power_usd_per_kwh: 0.08,
  colo_usd_per_kw_month: 150,
  ops_pct_per_year: 0.08,
  idle_power_fraction: 0.35,
};

const round = (v, digits = 2) => Math.round((v + Number.EPSILON) * 10 ** digits) / 10 ** digits;

export function buildVsRent(a, gpuCount, utilization, rent) {
  if (gpuCount < 1 || !(utilization > 0 && utilization <= 1) || !(rent > 0)) {
    throw new Error("need gpuCount >= 1, 0 < utilization <= 1 and a positive rent rate");
  }
  const servers = Math.ceil(gpuCount / GPUS_PER_SERVER);
  const capex = a.capex_per_server_usd * servers;
  const kw = a.server_kw * servers;

  const depreciation = capex / (a.depreciation_years * 12);
  const capital = (capex * a.cost_of_capital) / 2 / 12;
  const colocation = kw * a.colo_usd_per_kw_month;
  const operations = (capex * a.ops_pct_per_year) / 12;
  const energyPerLoad = kw * a.pue * HOURS_PER_MONTH * a.power_usd_per_kwh;
  const load = a.idle_power_fraction + (1 - a.idle_power_fraction) * utilization;
  const energy = energyPerLoad * load;

  const ownMonthly = depreciation + capital + colocation + operations + energy;
  const usefulGpuHours = gpuCount * HOURS_PER_MONTH * utilization;
  const rentMonthly = rent * usefulGpuHours;

  const fixed = depreciation + capital + colocation + operations;
  const intercept = fixed + energyPerLoad * a.idle_power_fraction;
  const slopeGap = rent * gpuCount * HOURS_PER_MONTH - energyPerLoad * (1 - a.idle_power_fraction);
  let breakeven = slopeGap > 0 ? intercept / slopeGap : null;
  if (breakeven !== null && breakeven > 1) breakeven = null;

  const horizon = Math.round(a.depreciation_years * 12);
  const cashMonthly = ownMonthly - depreciation;
  const ownCumulative = [], rentCumulative = [];
  for (let m = 0; m <= horizon; m++) {
    ownCumulative.push(capex + cashMonthly * m);
    rentCumulative.push(rentMonthly * m);
  }
  let paybackMonth = null;
  for (let m = 1; m <= horizon; m++) {
    if (ownCumulative[m] <= rentCumulative[m]) { paybackMonth = m; break; }
  }

  return {
    gpu_count: gpuCount,
    servers,
    utilization,
    rent_usd_per_gpu_hour: rent,
    own_usd_per_gpu_hour: round(ownMonthly / usefulGpuHours, 4),
    own_monthly_usd: round(ownMonthly),
    rent_monthly_usd: round(rentMonthly),
    own_monthly_breakdown_usd: {
      depreciation: round(depreciation),
      capital: round(capital),
      colocation: round(colocation),
      operations: round(operations),
      energy: round(energy),
    },
    breakeven_utilization: breakeven === null ? null : round(breakeven, 4),
    horizon_months: horizon,
    payback_month: paybackMonth,
    horizon_savings_usd: round(rentCumulative[horizon] - ownCumulative[horizon]),
    own_cumulative_usd: ownCumulative.map((v) => round(v)),
    rent_cumulative_usd: rentCumulative.map((v) => round(v)),
  };
}

// Own cost per useful GPU-hour across a utilization range, for the curve chart.
export function costCurve(a, gpuCount, rent, steps = 40) {
  const points = [];
  for (let i = 1; i <= steps; i++) {
    const u = 0.05 + (0.95 * (i - 1)) / (steps - 1);
    points.push([u, buildVsRent(a, gpuCount, u, rent).own_usd_per_gpu_hour]);
  }
  return points;
}
