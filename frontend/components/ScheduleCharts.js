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

const LOCALE = 'en-GB'
const TZ = 'Europe/London'

// Format a Date in Europe/London (the device/site timezone) for chart labels
const fmtTime = (dt) => dt.toLocaleTimeString(LOCALE, {
  hour: '2-digit', minute: '2-digit', hour12: false, timeZone: TZ,
})

const NOW_ANNOTATION = (label) => label ? {
  now: {
    type: 'line',
    xMin: label,
    xMax: label,
    borderColor: '#6B7280',
    borderWidth: 2,
    borderDash: [6, 3],
    label: { display: false },
  },
} : {}

const COMMON_OPTIONS = (nowLabel, keyToLabel = {}) => ({
  responsive: true,
  maintainAspectRatio: false,
  interaction: { mode: 'index', intersect: false },
  plugins: {
    legend: { position: 'bottom', labels: { boxWidth: 12, font: { size: 11 } } },
    annotation: { annotations: NOW_ANNOTATION(nowLabel) },
  },
  scales: {
    x: {
      ticks: {
        maxRotation: 90, minRotation: 90, font: { size: 9 }, autoSkip: false,
        callback: function(val, idx) {
          const key = this.getLabelForValue(val)
          return keyToLabel[key] || key
        },
      },
      grid: { display: false },
    },
  },
})

export default function ScheduleCharts({ schedule, historicData, nowTime, dayPrices = [] }) {
  if (!schedule || schedule.length === 0) return null

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

  const forecast = schedule.map((period) => {
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

  // Helper: build a single merged series with segment-based dashing
  function mergedSeries(label, color, histKey, fcstKey, yAxisID = 'y') {
    const data = labels.map(l => {
      if (historicMap[l] && historicMap[l][histKey] !== undefined) return historicMap[l][histKey]
      if (forecastMap[l] && forecastMap[l][fcstKey] !== undefined) return forecastMap[l][fcstKey]
      return null
    })
    return {
      label,
      data,
      borderColor: color,
      backgroundColor: color,
      borderWidth: 2,
      pointRadius: 0,
      tension: 0.3,
      yAxisID,
      segment: {
        borderDash: (ctx) => {
          const i = ctx.p0DataIndex
          const time = labels[i]
          return forecastMap[time] ? [8, 4] : undefined
        },
      },
    }
  }

  // ---- Chart 1: Solar, Demand & Price ----
  const solarData = {
    labels,
    datasets: [
      mergedSeries('Solar (kWh)', '#FBBF24', 'pv_kwh', 'pv_estimate'),
      mergedSeries('Demand (kWh)', '#A78BFA', 'load_kwh', 'demand'),
      mergedSeries('Grid Import (kWh)', '#EF4444', 'grid_import_kwh', 'grid_import'),
      { label: 'Import Price (p/kWh)', data: labels.map(l => priceMap[l]?.price ?? null), borderColor: '#FB923C', backgroundColor: '#FB923C', borderWidth: 1.5, pointRadius: 0, tension: 0.3, yAxisID: 'y1' },
      { label: 'Export Price (p/kWh)', data: labels.map(l => priceMap[l]?.export_price ?? null), borderColor: '#34D399', backgroundColor: '#34D399', borderWidth: 1.5, pointRadius: 0, tension: 0.3, yAxisID: 'y1' },
    ],
  }

  const solarOptions = {
    ...COMMON_OPTIONS(nowLabel, keyToLabel),
    scales: {
      ...COMMON_OPTIONS(nowLabel, keyToLabel).scales,
      y: { position: 'left', title: { display: true, text: 'kWh' } },
      y1: { position: 'right', title: { display: true, text: 'pence/kWh' }, grid: { drawOnChartArea: false } },
    },
  }

  // ---- Chart 2: Battery SOC ----
  const socData = {
    labels,
    datasets: [
      mergedSeries('SOC (%)', '#3B82F6', 'soc_pct', 'soc_pct'),
    ],
  }

  const socOptions = {
    ...COMMON_OPTIONS(nowLabel, keyToLabel),
    scales: {
      ...COMMON_OPTIONS(nowLabel, keyToLabel).scales,
      y: { min: 0, max: 100, title: { display: true, text: 'SOC (%)' } },
    },
  }

  // ---- Chart 3: Battery Actions (bars) ----
  const actionsData = {
    labels,
    datasets: [
      { label: 'Charge (kWh)', data: labels.map(l => historicMap[l]?.charge_kwh ?? forecastMap[l]?.batt_charge ?? null), backgroundColor: '#10B981' },
      { label: 'Discharge (kWh)', data: labels.map(l => historicMap[l]?.discharge_kwh ?? forecastMap[l]?.batt_discharge ?? null), backgroundColor: '#F59E0B' },
    ],
  }

  const actionsOptions = {
    ...COMMON_OPTIONS(nowLabel, keyToLabel),
    scales: {
      ...COMMON_OPTIONS(nowLabel, keyToLabel).scales,
      y: { title: { display: true, text: 'Energy (kWh)' } },
    },
  }

  // ---- Chart 4: Grid Energy (bars) ----
  const gridData = {
    labels,
    datasets: [
      { label: 'Grid Import (kWh)', data: labels.map(l => historicMap[l]?.grid_import_kwh ?? forecastMap[l]?.grid_import ?? null), backgroundColor: '#EF4444' },
      { label: 'Grid Export (kWh)', data: labels.map(l => forecastMap[l]?.grid_export ?? null), backgroundColor: '#22C55E' },
    ],
  }

  const gridOptions = {
    ...COMMON_OPTIONS(nowLabel, keyToLabel),
    scales: {
      ...COMMON_OPTIONS(nowLabel, keyToLabel).scales,
      y: { title: { display: true, text: 'Energy (kWh)' } },
    },
  }

  // ---- Chart 5: Cumulative Cost ----
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
    datasets: [
      { label: 'Cumulative Cost (£)', data: filledCostData, borderColor: '#8B5CF6', backgroundColor: '#8B5CF6', borderWidth: 2, pointRadius: 0, tension: 0.3, spanGaps: true },
    ],
  }

  const costOptions = {
    ...COMMON_OPTIONS(nowLabel, keyToLabel),
    scales: {
      ...COMMON_OPTIONS(nowLabel, keyToLabel).scales,
      y: { title: { display: true, text: 'Cost (£)' } },
    },
    plugins: {
      ...COMMON_OPTIONS(nowLabel, keyToLabel).plugins,
      tooltip: {
        callbacks: {
          label: (ctx) => `${ctx.dataset.label}: £${Number(ctx.parsed.y).toFixed(2)}`,
        },
      },
    },
  }

  return (
    <div className="space-y-8">
      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Solar, Demand & Price</h3>
        <div style={{ height: 300 }}><Line data={solarData} options={solarOptions} /></div>
      </div>
      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Battery State of Charge</h3>
        <div style={{ height: 250 }}><Line data={socData} options={socOptions} /></div>
      </div>
      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Battery Actions</h3>
        <div style={{ height: 300 }}><Bar data={actionsData} options={actionsOptions} /></div>
      </div>
      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Grid Energy</h3>
        <div style={{ height: 300 }}><Bar data={gridData} options={gridOptions} /></div>
      </div>
      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Cumulative Cost</h3>
        <div style={{ height: 250 }}><Line data={costData} options={costOptions} /></div>
      </div>
    </div>
  )
}
