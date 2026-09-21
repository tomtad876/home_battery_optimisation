import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  Title,
  Tooltip,
  Legend,
  Filler,
} from 'chart.js'
import annotationPlugin from 'chartjs-plugin-annotation'
import { Line, Bar } from 'react-chartjs-2'

ChartJS.register(
  CategoryScale, LinearScale, PointElement, LineElement,
  BarElement, Title, Tooltip, Legend, Filler, annotationPlugin
)

// ---------------------------------------------------------------------------
// Design tokens. Chart.js needs literal values (it paints to a canvas), so
// these mirror frontend/tailwind.config.js — keep the two in step.
// Colour is a code: chrome is monochrome, colour belongs to data.
//   signal = brand + battery charging   solar = generation   load = demand
//   gridin / gridout = grid flows       discharge = battery discharging
// ---------------------------------------------------------------------------
const T = {
  canvas: '#0B0F17',
  surface2: '#171E2A',
  hairline: '#202938',
  ink: '#E7ECF5',
  inkMuted: '#8B95A7',
  inkFaint: '#5A6376',
  signal: '#C3F53C',
  solar: '#FFA51F',
  load: '#64748B',
  gridIn: '#F87171',
  gridOut: '#34D399',
  discharge: '#A78BFA',
  warn: '#F0B429',
  // diverging price scale (cheap -> median -> peak)
  priceCheap: '#0E7490',
  pricePeak: '#DC2626',
}

ChartJS.defaults.color = T.inkMuted
ChartJS.defaults.font.family =
  'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif'
ChartJS.defaults.font.size = 11

// hex + alpha -> rgba, so every colour can be tinted without extra tokens
function hexA(hex, a) {
  const h = hex.replace('#', '')
  const full = h.length === 3 ? h.split('').map((c) => c + c).join('') : h
  const n = parseInt(full, 16)
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`
}

// Soft vertical gradient fill — depth without muddiness
function areaFill(color, topAlpha = 0.3) {
  return (context) => {
    const { chart } = context
    const { ctx, chartArea } = chart
    if (!chartArea) return hexA(color, topAlpha * 0.5)
    const g = ctx.createLinearGradient(0, chartArea.top, 0, chartArea.bottom)
    g.addColorStop(0, hexA(color, topAlpha))
    g.addColorStop(1, hexA(color, 0))
    return g
  }
}

// ONE treatment for "this is a forecast", applied to the whole region right of
// NOW — instead of dashing every series as it crosses the boundary.
const forecastHatch = {
  id: 'forecastHatch',
  beforeDatasetsDraw(chart, _args, opts) {
    const index = opts && opts.nowIndex
    if (index === null || index === undefined || index < 0) return
    const { ctx, chartArea } = chart
    const x = chart.scales && chart.scales.x
    if (!ctx || !chartArea || !x) return
    const startX = x.getPixelForValue(index)
    if (!Number.isFinite(startX)) return

    ctx.save()
    ctx.beginPath()
    ctx.rect(startX, chartArea.top, chartArea.right - startX, chartArea.bottom - chartArea.top)
    ctx.clip()
    ctx.strokeStyle = hexA(T.ink, 0.05)
    ctx.lineWidth = 1.5
    const span = chartArea.bottom - chartArea.top
    for (let px = startX - span; px < chartArea.right + span; px += 9) {
      ctx.beginPath()
      ctx.moveTo(px, chartArea.bottom)
      ctx.lineTo(px + span, chartArea.top)
      ctx.stroke()
    }
    ctx.restore()
  },
}

const LOCALE = 'en-GB'
const TZ = 'Europe/London'

// Format a Date in Europe/London (the device/site timezone) for chart labels
const fmtTime = (dt) => dt.toLocaleTimeString(LOCALE, {
  hour: '2-digit', minute: '2-digit', hour12: false, timeZone: TZ,
})

// 1px "now" line with a small pill — history sits left, forecast right
const NOW_ANNOTATION = (label) => label ? {
  now: {
    type: 'line',
    xMin: label,
    xMax: label,
    borderColor: hexA(T.ink, 0.5),
    borderWidth: 1,
    label: {
      display: true,
      content: 'NOW',
      position: 'start',
      backgroundColor: T.ink,
      color: T.canvas,
      font: { size: 9, weight: '700' },
      padding: { top: 3, bottom: 2, left: 6, right: 6 },
      borderRadius: 6,
      yAdjust: -2,
    },
  },
} : {}

const TOOLTIP = {
  backgroundColor: T.surface2,
  borderColor: T.hairline,
  borderWidth: 1,
  titleColor: T.ink,
  bodyColor: T.inkMuted,
  padding: 10,
  cornerRadius: 8,
  boxPadding: 4,
  usePointStyle: true,
}

const COMMON_OPTIONS = (nowLabel, keyToLabel = {}, { extraAnnotations = {}, nowIndex = null, legend = true, y = {} } = {}) => ({
  responsive: true,
  maintainAspectRatio: false,
  interaction: { mode: 'index', intersect: false },
  layout: { padding: { top: 18 } }, // room for the NOW pill
  plugins: {
    legend: legend ? {
      position: 'bottom',
      align: 'start',
      labels: {
        usePointStyle: true,
        pointStyle: 'rectRounded',
        boxWidth: 8,
        boxHeight: 8,
        padding: 16,
        color: T.inkMuted,
        font: { size: 11 },
      },
    } : { display: false },
    tooltip: TOOLTIP,
    annotation: { annotations: { ...NOW_ANNOTATION(nowLabel), ...extraAnnotations } },
    forecastHatch: { nowIndex },
  },
  scales: {
    x: {
      border: { display: false },
      // no mesh; fine time lives in the tooltip
      grid: { display: false },
      ticks: {
        maxRotation: 0,
        minRotation: 0,
        autoSkip: true,
        maxTicksLimit: 9,
        color: T.inkFaint,
        font: { size: 10 },
        callback: function (val) {
          const key = this.getLabelForValue(val)
          return keyToLabel[key] || key
        },
      },
    },
    y: {
      border: { display: false },
      grid: { color: hexA(T.ink, 0.07), drawTicks: false },
      ticks: { color: T.inkFaint, font: { size: 10 }, padding: 8, maxTicksLimit: 4 },
      ...y,
    },
  },
})

function ChartCard({ title, hint, children, footer }) {
  return (
    <div className="bg-surface border border-hairline rounded-card shadow-card p-5">
      <div className="flex items-baseline justify-between gap-3 mb-4">
        <h3 className="text-sm font-semibold text-ink">{title}</h3>
        {hint && <span className="text-xs text-ink-faint">{hint}</span>}
      </div>
      {children}
      {footer}
    </div>
  )
}

export default function ScheduleCharts({ schedule, historicData, nowTime, dayPrices = [], showEstimated = false }) {
  if (!schedule || schedule.length === 0) return null

  // The schedule may include a backfilled-price tail (is_synthetic). Hide it by
  // default; the test-env toggle reveals it, marked with an "estimated" boundary.
  const shown = showEstimated ? schedule : schedule.filter((s) => !s.is_synthetic)
  if (shown.length === 0) return null

  // Normalize any datetime string to a consistent ISO key for map lookups
  function isoKey(s) { return new Date(s).toISOString() }

  const nowMs = nowTime ? new Date(nowTime).getTime() : Date.now()

  const historic = (historicData || []).map((d) => {
    const dt = new Date(d.time)
    return {
      _iso: isoKey(d.time), _raw: dt.getTime(),
      time: fmtTime(dt),
      soc_pct: d.soc_pct !== undefined ? Number(d.soc_pct) : undefined,
      charge_kwh: d.charge_kwh !== undefined ? Number(d.charge_kwh) : undefined,
      discharge_kwh: d.discharge_kwh !== undefined ? Number(d.discharge_kwh) : undefined,
      grid_import_kwh: d.grid_import_kwh !== undefined ? Number(d.grid_import_kwh) : undefined,
      load_kwh: d.load_kwh !== undefined ? Number(d.load_kwh) : undefined,
      pv_kwh: d.pv_kwh !== undefined ? Number(d.pv_kwh) : undefined,
      import_price: d.import_price !== undefined ? Number(d.import_price) : undefined,
      export_price: d.export_price !== undefined ? Number(d.export_price) : undefined,
    }
  }).filter((d) => d._raw <= nowMs)

  const forecast = shown.map((period) => {
    const t = new Date(period.period_end)
    return {
      _iso: isoKey(period.period_end), _raw: t.getTime(),
      time: fmtTime(t),
      pv_estimate: Number(period.pv_estimate || 0),
      demand: Number(period.demand || 0),
      price: Number(period.price || 0),
      export_price: Number(period.export_price_pence ?? period.export_price ?? 0),
      soc_pct: Number(period.soc_pct || 0),
      batt_charge: Number(period.batt_charge_kwh || 0),
      batt_discharge: Number(period.batt_discharge_kwh || 0),
      grid_import: Number(period.grid_import_kwh || 0),
      grid_export: Number(period.grid_export_kwh || 0),
      is_synthetic: !!period.is_synthetic,
    }
  })

  // "Now" sits at the last historic point — where real data ends and forecast begins
  const nowLabel = historic.length > 0 ? historic[historic.length - 1]._iso : null

  // Build sorted label array using full ISO date keys to avoid day collisions
  const allTimes = [...historic.map(h => ({ key: h._iso, time: h.time, _raw: h._raw })),
    ...forecast.map(f => ({ key: f._iso, time: f.time, _raw: f._raw }))]
    .sort((a, b) => a._raw - b._raw)
  const seen = new Set()
  const labels = []
  const keyToLabel = {}
  for (const t of allTimes) {
    if (!seen.has(t.key)) {
      seen.add(t.key)
      labels.push(t.key)
      keyToLabel[t.key] = t.time
    }
  }

  // Build lookup maps using ISO keys
  const historicMap = Object.fromEntries(historic.map(h => [h._iso, h]))
  const forecastMap = Object.fromEntries(forecast.map(f => [f._iso, f]))

  // Prices: build priceMap using ISO keys, then forecast overrides historic
  const priceMap = {}
  for (const h of historic) {
    if (h.import_price !== undefined) {
      priceMap[h._iso] = { price: h.import_price, export_price: h.export_price ?? 0 }
    }
  }
  for (const p of dayPrices) {
    const key = isoKey(p.period_end)
    priceMap[key] = {
      price: Number(p.import_price || 0),
      export_price: Number(p.export_price || 0),
    }
  }

  // Index of NOW within the label array (-1 if there is no history at all,
  // in which case the whole window is a forecast and we hatch from the start)
  const rawNow = nowLabel ? labels.indexOf(nowLabel) : -1
  const nowIndex = historic.length === 0 ? 0 : (rawNow >= 0 ? rawNow : null)

  // Helper: build a single merged series (history then forecast, no per-series
  // dashing — the forecast region is marked once by the hatch)
  function mergedSeries(label, color, histKey, fcstKey, opts = {}) {
    const data = labels.map(l => {
      if (historicMap[l] && historicMap[l][histKey] !== undefined) return historicMap[l][histKey]
      if (forecastMap[l] && forecastMap[l][fcstKey] !== undefined) return forecastMap[l][fcstKey]
      return null
    })
    return {
      label,
      data,
      borderColor: color,
      backgroundColor: opts.fill ? areaFill(color, opts.fillAlpha ?? 0.3) : color,
      fill: opts.fill ? 'origin' : false,
      borderWidth: opts.width ?? 2,
      pointRadius: 0,
      pointHoverRadius: 3,
      tension: opts.tension ?? 0.25,
      spanGaps: true,
      yAxisID: 'y',
    }
  }

  // Boundary between real published prices and the backfilled/estimated tail.
  const firstSynthetic = forecast.find((f) => f.is_synthetic)
  const estimatedLabel = showEstimated && firstSynthetic ? firstSynthetic._iso : null
  const lastLabel = labels.length > 0 ? labels[labels.length - 1] : null
  // The boundary line is drawn on every chart (the whole tail is built on
  // estimated prices), but the text tag only on the price chart — it is a
  // label for the prices, not for the battery.
  const estAnnotations = (withLabel) => estimatedLabel ? {
    estimatedLine: {
      type: 'line',
      xMin: estimatedLabel,
      xMax: estimatedLabel,
      borderColor: hexA(T.warn, 0.8),
      borderWidth: 1,
      borderDash: [6, 4],
      label: {
        display: !!withLabel,
        content: 'estimated prices',
        position: 'start',
        backgroundColor: hexA(T.warn, 0.92),
        color: T.canvas,
        font: { size: 10 },
        padding: { top: 2, bottom: 2, left: 6, right: 6 },
        borderRadius: 6,
      },
    },
    estimatedRegion: {
      type: 'box',
      xMin: estimatedLabel,
      xMax: lastLabel,
      backgroundColor: hexA(T.warn, 0.05),
      borderWidth: 0,
    },
  } : {}

  // ---- Chart 1: Solar & demand (flows) --------------------------------------
  const flowsData = {
    labels,
    datasets: [
      mergedSeries('Solar kWh', T.solar, 'pv_kwh', 'pv_estimate', { fill: true, fillAlpha: 0.3, tension: 0.3 }),
      mergedSeries('Demand kWh', T.load, 'load_kwh', 'demand', { width: 1.5, tension: 0.3 }),
    ],
  }
  const flowsOptions = COMMON_OPTIONS(nowLabel, keyToLabel, { extraAnnotations: estAnnotations(false), nowIndex })

  // ---- Chart 2: Price heat strip -------------------------------------------
  // Prices are a continuous condition, so they get a background heat strip with
  // a diverging scale around the median of the window, not a line.
  const priceValues = labels.map(l => priceMap[l]?.price ?? forecastMap[l]?.price ?? null)
  const present = priceValues.filter(v => v !== null && v !== undefined)
  const ordered = [...present].sort((a, b) => a - b)
  const pMin = ordered.length ? ordered[0] : 0
  const pMax = ordered.length ? ordered[ordered.length - 1] : 1
  const pMed = ordered.length ? ordered[Math.floor(ordered.length / 2)] : 0

  function priceColor(p) {
    if (p === null || p === undefined) return hexA(T.ink, 0.04)
    if (p >= pMed) {
      const t = pMax > pMed ? (p - pMed) / (pMax - pMed) : 0
      return hexA(T.pricePeak, 0.16 + 0.74 * t)
    }
    const t = pMed > pMin ? (p - pMin) / (pMed - pMin) : 0
    return hexA(T.priceCheap, 0.16 + 0.74 * t)
  }

  const priceData = {
    labels,
    datasets: [{
      label: 'Import price',
      data: labels.map(() => 1),
      backgroundColor: priceValues.map(priceColor),
      borderWidth: 0,
      borderRadius: 2,
      borderSkipped: false,
      barPercentage: 1.0,
      categoryPercentage: 0.94,
    }],
  }

  const priceOptions = COMMON_OPTIONS(nowLabel, keyToLabel, {
    extraAnnotations: estAnnotations(true),
    nowIndex,
    legend: false,
    y: { display: false, grid: { display: false }, max: 1 },
  })
  priceOptions.plugins.tooltip = {
    ...TOOLTIP,
    callbacks: {
      title: (items) => (items[0] ? keyToLabel[items[0].label] || items[0].label : ''),
      label: (ctx) => {
        const l = labels[ctx.dataIndex]
        const imp = priceMap[l]?.price ?? forecastMap[l]?.price
        const exp = priceMap[l]?.export_price ?? forecastMap[l]?.export_price
        const out = []
        if (imp !== null && imp !== undefined) out.push(`Import ${Number(imp).toFixed(1)}p/kWh`)
        if (exp !== null && exp !== undefined) out.push(`Export ${Number(exp).toFixed(1)}p/kWh`)
        return out
      },
    },
  }

  // ---- Chart 3: Battery state of charge ------------------------------------
  const socData = {
    labels,
    datasets: [
      mergedSeries('State of charge %', T.signal, 'soc_pct', 'soc_pct', { fill: true, fillAlpha: 0.34 }),
    ],
  }
  const socOptions = COMMON_OPTIONS(nowLabel, keyToLabel, {
    extraAnnotations: estAnnotations(false),
    nowIndex,
    legend: false,
    y: { min: 0, max: 100, ticks: { color: T.inkFaint, font: { size: 10 }, padding: 8, stepSize: 50 } },
  })

  // ---- Chart 4: Battery actions (bars) -------------------------------------
  const barDataset = (label, color, pick) => ({
    label,
    data: labels.map(pick),
    backgroundColor: hexA(color, 0.85),
    hoverBackgroundColor: hexA(color, 1),
    borderWidth: 0,
    borderRadius: 2,
    borderSkipped: false,
    barPercentage: 1.0,
    categoryPercentage: 0.9,
  })

  const actionsData = {
    labels,
    datasets: [
      barDataset('Charge kWh', T.signal, l => historicMap[l]?.charge_kwh ?? forecastMap[l]?.batt_charge ?? null),
      barDataset('Discharge kWh', T.discharge, l => historicMap[l]?.discharge_kwh ?? forecastMap[l]?.batt_discharge ?? null),
    ],
  }
  const actionsOptions = COMMON_OPTIONS(nowLabel, keyToLabel, { extraAnnotations: estAnnotations(false), nowIndex })

  // ---- Chart 5: Grid energy (bars) -----------------------------------------
  const gridData = {
    labels,
    datasets: [
      barDataset('Grid import kWh', T.gridIn, l => historicMap[l]?.grid_import_kwh ?? forecastMap[l]?.grid_import ?? null),
      barDataset('Grid export kWh', T.gridOut, l => forecastMap[l]?.grid_export ?? null),
    ],
  }
  const gridOptions = COMMON_OPTIONS(nowLabel, keyToLabel, { extraAnnotations: estAnnotations(false), nowIndex })

  // ---- Chart 6: Cumulative cost --------------------------------------------
  // Build cumulative cost across ALL labels (historic + forecast)
  let cumCost = 0
  const costDataPoints = labels.map((l) => {
    // Historic cost
    if (historicMap[l] && historicMap[l].import_price !== undefined) {
      const d = historicMap[l]
      const importCost = Number(d.grid_import_kwh || 0) * (Number(d.import_price || 0) / 100)
      // No export in historic — assume 0
      cumCost += importCost
      return cumCost
    }
    // Forecast cost
    if (forecastMap[l]) {
      const d = forecastMap[l]
      const importCost = Number(d.grid_import || 0) * (Number(d.price || 0) / 100)
      const exportRevenue = Number(d.grid_export || 0) * (Number(d.export_price || 0) / 100)
      cumCost += (importCost - exportRevenue)
      return cumCost
    }
    return null
  })

  // Fill nulls by carrying forward the last known cumulative cost
  let lastCost = 0
  const filledCostData = costDataPoints.map((v) => {
    if (v !== null) { lastCost = v }
    return lastCost
  })

  const costData = {
    labels,
    datasets: [{
      label: 'Cumulative cost £',
      data: filledCostData,
      borderColor: T.ink,
      backgroundColor: T.ink,
      borderWidth: 2,
      pointRadius: 0,
      pointHoverRadius: 3,
      tension: 0.25,
      spanGaps: true,
    }],
  }

  const costOptions = COMMON_OPTIONS(nowLabel, keyToLabel, {
    extraAnnotations: estAnnotations(false),
    nowIndex,
    legend: false,
  })
  costOptions.plugins.tooltip = {
    ...TOOLTIP,
    callbacks: {
      label: (ctx) => `Cumulative cost: £${Number(ctx.parsed.y).toFixed(2)}`,
    },
  }

  const priceKey = (
    <div className="flex items-center gap-3 mt-3 text-xs text-ink-faint">
      <span>cheap</span>
      <span
        className="h-2 w-40 rounded-full"
        style={{ background: `linear-gradient(90deg, ${T.priceCheap}, rgba(140,140,140,0.14), ${T.pricePeak})` }}
      />
      <span>peak</span>
      <span className="ml-auto">p/kWh · hover a half-hour for values</span>
    </div>
  )

  return (
    <div className="space-y-4">
      <ChartCard title="State of charge" hint="% of battery capacity">
        <div style={{ height: 240 }}>
          <Line data={socData} options={socOptions} plugins={[forecastHatch]} />
        </div>
      </ChartCard>

      <ChartCard title="Price" hint="import & export, half-hourly">
        <div style={{ height: 104 }}>
          <Bar data={priceData} options={priceOptions} plugins={[forecastHatch]} />
        </div>
        {priceKey}
      </ChartCard>

      <ChartCard title="Solar & demand" hint="kWh per half-hour">
        <div style={{ height: 240 }}>
          <Line data={flowsData} options={flowsOptions} plugins={[forecastHatch]} />
        </div>
      </ChartCard>

      <ChartCard title="Battery actions" hint="kWh per half-hour">
        <div style={{ height: 220 }}>
          <Bar data={actionsData} options={actionsOptions} plugins={[forecastHatch]} />
        </div>
      </ChartCard>

      <ChartCard title="Grid energy" hint="kWh per half-hour">
        <div style={{ height: 220 }}>
          <Bar data={gridData} options={gridOptions} plugins={[forecastHatch]} />
        </div>
      </ChartCard>

      <ChartCard title="Cumulative cost" hint="£ across the window">
        <div style={{ height: 220 }}>
          <Line data={costData} options={costOptions} plugins={[forecastHatch]} />
        </div>
      </ChartCard>
    </div>
  )
}
