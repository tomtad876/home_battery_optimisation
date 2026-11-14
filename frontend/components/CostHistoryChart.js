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
import { Bar } from 'react-chartjs-2'

ChartJS.register(
  CategoryScale, LinearScale, PointElement, LineElement,
  BarElement, Title, Tooltip, Legend, Filler, annotationPlugin
)

// Mirrors frontend/tailwind.config.js — Chart.js paints to a canvas, so it
// needs literal values. Colour is a code: chrome monochrome, colour = data.
const T = {
  surface2: '#171E2A',
  hairline: '#202938',
  ink: '#E7ECF5',
  inkMuted: '#8B95A7',
  inkFaint: '#5A6376',
  gridIn: '#F87171',
  gridOut: '#34D399',
  load: '#64748B',
  solar: '#FFA51F',
}

const money = (v) => {
  const n = Number(v || 0)
  const abs = Math.abs(n).toFixed(2)
  return `${n < 0 ? '−' : ''}£${abs}`
}

const shortDay = (iso) =>
  new Date(`${iso}T12:00:00Z`).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })

/**
 * Daily cost history. Import and standing charges stack upwards, export income
 * hangs below the axis, and the net line is what the day actually cost.
 * Cumulative mode switches to running totals so "all time" has a shape.
 */
export default function CostHistoryChart({ days, mode = 'daily' }) {
  if (!days || days.length === 0) return null

  const labels = days.map((d) => shortDay(d.day))
  const cumulative = mode === 'cumulative'

  let runNet = 0
  let runValue = 0
  const net = []
  const value = []
  for (const d of days) {
    const n = Number(d.net_cost_gbp || 0)
    const v = Number(d.total_value_gbp || 0)
    if (cumulative) {
      runNet += n
      runValue += v
      net.push(Number(runNet.toFixed(2)))
      value.push(Number(runValue.toFixed(2)))
    } else {
      net.push(Number(n.toFixed(2)))
      value.push(Number(v.toFixed(2)))
    }
  }

  // Tariff changes become vertical markers; only where the label actually moves.
  const annotations = {}
  let prevLabel = null
  days.forEach((d, i) => {
    if (d.tariff_label && prevLabel && d.tariff_label !== prevLabel) {
      annotations[`t${i}`] = {
        type: 'line',
        xMin: labels[i],
        xMax: labels[i],
        borderColor: T.inkFaint,
        borderWidth: 1,
        borderDash: [4, 4],
        label: {
          display: true,
          content: d.tariff_label,
          position: 'end',
          yAdjust: 8,
          color: T.inkMuted,
          backgroundColor: 'rgba(11,15,23,0.85)',
          font: { size: 10 },
          padding: 4,
        },
      }
    }
    if (d.tariff_label) prevLabel = d.tariff_label
  })

  const datasets = cumulative
    ? [
        {
          type: 'line',
          label: 'Saved vs no kit (£, cumulative)',
          data: value,
          borderColor: T.solar,
          backgroundColor: 'rgba(255,165,31,0.12)',
          fill: true,
          tension: 0.25,
          pointRadius: 0,
          borderWidth: 2,
        },
        {
          type: 'line',
          label: 'Net energy cost (£, cumulative)',
          data: net,
          borderColor: T.ink,
          borderWidth: 1.5,
          pointRadius: 0,
          tension: 0.25,
          fill: false,
        },
      ]
    : [
        {
          label: 'Import',
          data: days.map((d) => Number(Number(d.import_cost_gbp || 0).toFixed(2))),
          backgroundColor: T.gridIn,
          stack: 'cost',
        },
        {
          label: 'Standing charge',
          data: days.map((d) => Number(Number(d.standing_gbp || 0).toFixed(2))),
          backgroundColor: T.load,
          stack: 'cost',
        },
        {
          label: 'Export income',
          data: days.map((d) => Number((-Number(d.export_income_gbp || 0)).toFixed(2))),
          backgroundColor: T.gridOut,
          stack: 'cost',
        },
        {
          type: 'line',
          label: 'Net cost',
          data: net,
          borderColor: T.ink,
          borderWidth: 1.5,
          pointRadius: 0,
          tension: 0.2,
          fill: false,
        },
      ]

  return (
    <div className="h-60 sm:h-72">
      <Bar
        data={{ labels, datasets }}
        options={{
          responsive: true,
          maintainAspectRatio: false,
          interaction: { mode: 'index', intersect: false },
          plugins: {
            legend: {
              labels: { color: T.inkMuted, boxWidth: 10, boxHeight: 10, font: { size: 11 } },
              position: 'bottom',
            },
            tooltip: {
              backgroundColor: T.surface2,
              borderColor: T.hairline,
              borderWidth: 1,
              titleColor: T.ink,
              bodyColor: T.inkMuted,
              callbacks: {
                label: (ctx) => `${ctx.dataset.label}: ${money(ctx.parsed.y)}`,
              },
            },
            annotation: {
              annotations,
              // annotation plugin colours come from the annotation objects above
            },
          },
          scales: {
            x: {
              stacked: !cumulative,
              grid: { color: 'rgba(32,41,56,0.6)', drawTicks: false },
              ticks: {
                color: T.inkMuted,
                font: { size: 10 },
                maxRotation: 0,
                autoSkip: true,
                maxTicksLimit: 10,
              },
            },
            y: {
              stacked: !cumulative,
              grid: { color: T.hairline },
              ticks: {
                color: T.inkMuted,
                font: { size: 10 },
                callback: (v) => money(v),
              },
            },
          },
        }}
      />
    </div>
  )
}
