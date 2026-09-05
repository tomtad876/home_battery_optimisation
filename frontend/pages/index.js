import Head from 'next/head'
import OptimiserForm from '@/components/OptimiserForm'
import ScheduleCharts from '@/components/ScheduleCharts'
import AuthForm from '@/components/AuthForm'
import SetupWizard from '@/components/SetupWizard'
import { supabase } from '@/lib/supabaseClient'
import { useState, useEffect, useRef, useCallback } from 'react'

export default function Home() {
  const [schedule, setSchedule] = useState(null)
  const [summary, setSummary] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [user, setUser] = useState(null)
  const [site, setSite] = useState(null)
  const [siteLoading, setSiteLoading] = useState(true)
  const checkedSessionRef = useRef(false)

  const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

  const checkSite = useCallback(async (accessToken) => {
    if (!accessToken) {
      setSite(null)
      setSiteLoading(false)
      return
    }
    try {
      const res = await fetch(`${apiUrl}/sites/me`, {
        headers: { 'Authorization': `Bearer ${accessToken}` },
      })
      if (res.ok) {
        const data = await res.json()
        setSite(data.site)
      } else {
        setSite(null)
      }
    } catch {
      setSite(null)
    } finally {
      setSiteLoading(false)
    }
  }, [apiUrl])

  const handleOptimise = async (params) => {
    setLoading(true)
    setError(null)
    try {
      const { data: { session } } = await supabase.auth.getSession()
      const headers = { 'Content-Type': 'application/json' }
      if (session?.access_token) {
        headers['Authorization'] = `Bearer ${session.access_token}`
      }
      const response = await fetch(`${apiUrl}/optimise/mvp`, {
        method: 'POST',
        headers,
        body: JSON.stringify(params),
      })
      if (!response.ok) {
        const errorData = await response.json()
        const msg = errorData.detail || 'Optimisation failed'
        if (msg.startsWith('NO_DATA:')) {
          throw new Error('no_data')
        }
        throw new Error(msg)
      }
      const data = await response.json()
      setSummary(data.summary)
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
        export_price: r.export_price ?? r.export_price_pence ?? null,
      }))
      setSchedule(normalized)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    let mounted = true

    supabase.auth.getSession().then(({ data }) => {
      if (!mounted) return
      const u = data?.session?.user ?? null
      setUser(u)
      if (u && data?.session?.access_token) {
        checkSite(data.session.access_token)
      } else {
        setSiteLoading(false)
      }
      checkedSessionRef.current = true
    })

    const { data: listener } = supabase.auth.onAuthStateChange((event, session) => {
      if (!mounted) return

      if (event === 'SIGNED_IN') {
        setUser(session?.user ?? null)
        if (session?.access_token) {
          setSiteLoading(true)
          checkSite(session.access_token)
        }
      } else if (event === 'SIGNED_OUT') {
        setUser(null)
        setSite(null)
        setSchedule(null)
        setSummary(null)
        setSiteLoading(false)
      }
    })

    return () => {
      mounted = false
      listener?.subscription?.unsubscribe && listener.subscription.unsubscribe()
    }
  }, [checkSite])

  const handleLogout = async () => {
    await supabase.auth.signOut()
  }

  const handleSetupComplete = () => {
    supabase.auth.getSession().then(({ data }) => {
      if (data?.session?.access_token) {
        checkSite(data.session.access_token)
      }
    })
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

          {/* Not logged in */}
          {!user && (
            <div className="max-w-md mx-auto">
              <AuthForm onLogin={() => supabase.auth.getSession().then(({ data }) => setUser(data?.session?.user))} />
            </div>
          )}

          {/* Logged in, loading site check */}
          {user && siteLoading && (
            <div className="text-center py-12">
              <p className="text-gray-500">Loading...</p>
            </div>
          )}

          {/* Logged in, no site → setup wizard */}
          {user && !siteLoading && !site && (
            <SetupWizard apiUrl={apiUrl} onComplete={handleSetupComplete} />
          )}

          {/* Logged in, has site → dashboard */}
          {user && !siteLoading && site && (
            <>
              <div className="flex items-center justify-between mb-6">
                <p className="text-sm text-gray-600">Signed in as <span className="font-medium">{user?.email}</span></p>
                <button onClick={handleLogout} className="text-sm text-red-600 hover:text-red-800">Sign out</button>
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-4 gap-8">
                {/* Form Panel */}
                <div className="lg:col-span-1">
                  <div className="bg-white rounded-lg shadow p-6 sticky top-4">
                    <OptimiserForm onSubmit={handleOptimise} loading={loading} />
                  </div>
                </div>

                {/* Results Panel */}
                <div className="lg:col-span-3">
                  {error === 'no_data' ? (
                    <div className="bg-amber-50 border border-amber-200 rounded-lg p-6 mb-6">
                      <h3 className="text-amber-800 font-semibold mb-2">No forecast data yet</h3>
                      <p className="text-amber-700 mb-3">
                        We need your solar forecast and energy usage data to generate an optimisation schedule.
                      </p>
                      <p className="text-amber-600 text-sm">
                        Make sure your Solcast API key, Solcast PV System ID, and FoxESS API key are configured.
                        Data is fetched daily by our background services — it may take up to 24 hours after first setup.
                      </p>
                    </div>
                  ) : error ? (
                    <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-6">
                      <p className="text-red-800"><strong>Error:</strong> {error}</p>
                    </div>
                  ) : null}

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
                            £{formatNumber(summary?.total_grid_export_revenue_gbp ?? ((summary?.total_grid_export_kwh || 0) * 0.15 / 100), 2)}
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
            </>
          )}
        </div>
      </main>
    </>
  )
}
