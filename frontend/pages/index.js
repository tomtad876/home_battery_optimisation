import Head from 'next/head'
import OptimiserForm from '@/components/OptimiserForm'
import ScheduleCharts from '@/components/ScheduleCharts'
import { useState } from 'react'

export default function Home() {
  const [schedule, setSchedule] = useState(null)
  const [summary, setSummary] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const handleOptimise = async (params) => {
    setLoading(true)
    setError(null)
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
      const response = await fetch(`${apiUrl}/optimise/mvp`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params),
      })
      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.detail || 'Optimisation failed')
      }
      const data = await response.json()
      setSummary(data.summary)
      // Normalize schedule keys returned by backend to the frontend shape
      const normalized = (data.schedule || []).map((r) => ({
        period_end: r.PeriodEnd ?? r.period_end,
        pv_estimate: r.PvEstimate ?? r.solar ?? r.pv_estimate ?? 0,
        demand: r.demand ?? r.demand_kwh ?? 0,
        price: r.price ?? r.import_price ?? 0,
        soc_pct: r.soc_pct ?? r.socPct ?? 0,
        batt_charge_kwh: r.batt_charge_kwh ?? r.batt_charge ?? 0,
        batt_discharge_kwh: r.batt_discharge_kwh ?? r.batt_discharge ?? 0,
        grid_import_kwh: r.grid_import_kwh ?? r.grid_import ?? 0,
        grid_export_kwh: r.grid_export_kwh ?? r.grid_export ?? 0,
        cost_gbp: r.cost_gbp ?? r.cost ?? 0,
      }))
      setSchedule(normalized)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const formatNumber = (v, decimals) => {
    if (v === undefined || v === null || Number.isNaN(Number(v))) return (0).toFixed(decimals)
    return Number(v).toFixed(decimals)
  }

  return (
    <>
      <Head>
        <title>Battery Optimiser</title>
        <meta name="description" content="Optimise battery schedules for lowest cost" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
      </Head>
      <main className="min-h-screen bg-gray-50">
        <div className="max-w-7xl mx-auto py-12 px-4">
          <header className="mb-12">
            <h1 className="text-4xl font-bold text-gray-900">Battery Optimiser</h1>
            <p className="text-gray-600 mt-2">Minimise electricity costs with intelligent battery dispatch</p>
          </header>

          <div className="grid grid-cols-1 lg:grid-cols-4 gap-8">
            {/* Form Panel */}
            <div className="lg:col-span-1">
              <div className="bg-white rounded-lg shadow p-6 sticky top-4">
                <OptimiserForm onSubmit={handleOptimise} loading={loading} />
              </div>
            </div>

            {/* Results Panel */}
            <div className="lg:col-span-3">
              {error && (
                <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-6">
                  <p className="text-red-800"><strong>Error:</strong> {error}</p>
                </div>
              )}

              {summary && schedule && (
                <>
                  {/* Summary Cards */}
                  <div className="grid grid-cols-2 gap-4 mb-6">
                    <div className="bg-white rounded-lg shadow p-4">
                      <p className="text-sm text-gray-600">Total Cost</p>
                      <p className="text-2xl font-bold text-blue-600">
                        £{formatNumber(summary?.total_cost_gbp, 2)}
                      </p>
                    </div>
                    <div className="bg-white rounded-lg shadow p-4">
                      <p className="text-sm text-gray-600">Grid Export Revenue</p>
                      <p className="text-2xl font-bold text-green-600">
                        £{formatNumber((summary?.total_grid_export_kwh || 0) * 0.15 / 100, 2)}
                      </p>
                    </div>
                    <div className="bg-white rounded-lg shadow p-4">
                      <p className="text-sm text-gray-600">Solar Generation</p>
                      <p className="text-2xl font-bold text-yellow-600">
                        {formatNumber(summary?.total_solar_kwh, 1)} kWh
                      </p>
                    </div>
                    <div className="bg-white rounded-lg shadow p-4">
                      <p className="text-sm text-gray-600">Total Demand</p>
                      <p className="text-2xl font-bold text-purple-600">
                        {formatNumber(summary?.total_demand_kwh, 1)} kWh
                      </p>
                    </div>
                  </div>

                  {/* Charts */}
                  <ScheduleCharts schedule={schedule} />
                </>
              )}

              {!schedule && !loading && !error && (
                <div className="bg-white rounded-lg shadow p-12 text-center">
                  <p className="text-gray-500 text-lg">Enter parameters and click <strong>Optimise</strong> to see the schedule</p>
                </div>
              )}
            </div>
          </div>
        </div>
      </main>
    </>
  )
}
