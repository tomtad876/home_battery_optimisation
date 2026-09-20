import Head from 'next/head'
import ScheduleCharts from '@/components/ScheduleCharts'
import AuthForm from '@/components/AuthForm'
import SetupWizard from '@/components/SetupWizard'
import { supabase } from '@/lib/supabaseClient'
import { apiFetch, friendlyError } from '@/lib/api'
import { useState, useEffect, useRef, useCallback } from 'react'

// Test-environment only flag. NODE_ENV is 'development' under `next dev` and
// 'production' for any build (`next build`/`next start`/Vercel), so this toggle
// cannot leak into a production deployment.
const IS_DEV = process.env.NODE_ENV === 'development'

export default function Home() {
  const [schedule, setSchedule] = useState(null)
  const [summary, setSummary] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [user, setUser] = useState(null)
  const [site, setSite] = useState(null)
  const [siteLoading, setSiteLoading] = useState(true)
  const [siteError, setSiteError] = useState(null)
  const [serverWaking, setServerWaking] = useState(false)
  const [manualSoc, setManualSoc] = useState('')
  const [lastRunAt, setLastRunAt] = useState(null)
  const [realtimeData, setRealtimeData] = useState({ soc_pct: null, history: [], fetchedAt: null })
  const [dayPrices, setDayPrices] = useState([])
  const [pushing, setPushing] = useState(false)
  const [pushResult, setPushResult] = useState(null)
  const [previewing, setPreviewing] = useState(false)
  const [previewResult, setPreviewResult] = useState(null)
  const [showEstimated, setShowEstimated] = useState(false)
  const checkedSessionRef = useRef(false)
  const autoRanRef = useRef(false)

  const fetchRealtime = useCallback(async (accessToken) => {
    try {
      const data = await apiFetch('/battery/realtime', { accessToken })
      setRealtimeData({
        ...data,
        error: data?.error ?? null,
        fetchedAt: new Date().toISOString(),
      })
    } catch (err) {
      // Surface the failure — the dashboard renders realtimeData.error. Swallowing
      // it used to leave auto-optimise waiting on a SOC that never arrived, with
      // a placeholder and no explanation.
      setRealtimeData((prev) => ({
        ...prev,
        error: friendlyError(err, 'Live battery data unavailable.'),
      }))
    }
    // Also fetch today's prices (chart decoration — the optimiser result already
    // carries prices, so a failure here is not worth surfacing)
    try {
      const data = await apiFetch('/tariff/prices', { accessToken })
      setDayPrices(data?.prices || [])
    } catch {}
  }, [])

  const checkSite = useCallback(async (accessToken) => {
    if (!accessToken) {
      setSite(null)
      setSiteLoading(false)
      return
    }
    setSiteError(null)
    try {
      const data = await apiFetch('/sites/me', {
        accessToken,
        // Three attempts (~95s worst case) so a sleeping backend recovers on its
        // own. The loading copy says what's happening while it waits.
        retries: 2,
        onRetry: () => setServerWaking(true),
      })
      setSite(data?.site ?? null)
      if (data?.site) {
        fetchRealtime(accessToken)
      }
    } catch (err) {
      setSite(null)
      // 404 is the documented "no site yet" answer → send them to the wizard.
      // Anything else (timeout, network, 5xx) is a server problem, not a setup
      // problem; showing the wizard there would push an existing user back
      // through onboarding.
      if (err?.status !== 404) {
        setSiteError(friendlyError(err, 'Could not load your site.'))
      }
    } finally {
      setSiteLoading(false)
      setServerWaking(false)
    }
  }, [fetchRealtime])

  const handleOptimise = async (params) => {
    setLoading(true)
    setError(null)
    setServerWaking(false)
    try {
      const { data: { session } } = await supabase.auth.getSession()
      const data = await apiFetch('/optimise/mvp', {
        method: 'POST',
        body: params,
        accessToken: session?.access_token,
        onRetry: () => setServerWaking(true),
      })
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
        is_synthetic: !!r.is_synthetic,
      }))
      setSchedule(normalized)
      setLastRunAt(
        new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: 'Europe/London' })
      )
    } catch (err) {
      const message = friendlyError(err, 'Optimisation failed.')
      setError(message.includes('NO_DATA') ? 'no_data' : message)
    } finally {
      setLoading(false)
      setServerWaking(false)
    }
  }

  const handlePreview = async () => {
    setPreviewing(true)
    setPreviewResult(null)
    try {
      const { data: { session } } = await supabase.auth.getSession()
      if (!session?.access_token) {
        setPreviewResult({ success: false, error: 'Not logged in' })
        return
      }
      const data = await apiFetch('/optimise/push', {
        method: 'POST',
        accessToken: session.access_token,
        // Send only what the backend cannot infer. Battery parameters come from
        // the saved battery row (routes.py:348-353) — hardcoding them here
        // silently mis-optimised any user whose battery isn't 5 kWh / 3 kW.
        body: { preview: true },
      })
      setPreviewResult({
        success: true,
        soc: data.soc_at_push,
        remainMode: data.remain_mode,
        schedule: data.groups || [],
      })
    } catch (err) {
      setPreviewResult({ success: false, error: friendlyError(err, 'Preview failed.') })
    } finally {
      setPreviewing(false)
    }
  }

  const handlePush = async () => {
    setPushing(true)
    setPushResult(null)
    try {
      const { data: { session } } = await supabase.auth.getSession()
      if (!session?.access_token) {
        setPushResult({ success: false, error: 'Not logged in' })
        return
      }
      const data = await apiFetch('/optimise/push', {
        method: 'POST',
        accessToken: session.access_token,
        // Battery params from the saved battery row (see handlePreview).
        body: {},
        // Never retry a live push: a client-side timeout may mean the schedule
        // already reached the inverter, and a blind retry would push twice.
        retryUnsafe: false,
      })
      setPushResult({
        success: true,
        groups: data.groups_sent,
        soc: data.soc_at_push,
        schedule: data.groups || [],
      })
    } catch (err) {
      setPushResult({ success: false, error: friendlyError(err, 'Push failed.') })
    } finally {
      setPushing(false)
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

  // Auto-run optimiser once site and realtime data are loaded
  useEffect(() => {
    if (site && realtimeData.soc_pct !== null && !autoRanRef.current && !loading && !schedule) {
      autoRanRef.current = true
      // Only the initial SOC is genuinely unknown to the backend — the rest comes
      // from the saved battery row.
      handleOptimise({ initial_soc_pct: realtimeData.soc_pct })
    }
  }, [site, realtimeData.soc_pct])

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

  const retrySite = async () => {
    setSiteLoading(true)
    const { data } = await supabase.auth.getSession()
    await checkSite(data?.session?.access_token)
  }

  const hasLiveSoc = realtimeData.soc_pct !== null && realtimeData.soc_pct !== undefined

  // Manual (re-)run. Battery config comes from the saved battery row on the
  // backend — the only thing it cannot know is where the battery is right now,
  // so that's the one field offered here.
  const runOptimiser = () => {
    const soc = hasLiveSoc ? realtimeData.soc_pct : manualSoc === '' ? null : Number(manualSoc)
    handleOptimise(soc === null || Number.isNaN(soc) ? {} : { initial_soc_pct: soc })
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
              <p className="text-gray-500">
                {serverWaking ? 'Still waking the server — retrying…' : 'Connecting…'}
              </p>
              <p className="text-gray-400 text-sm mt-2">
                The server sleeps when idle, so the first request can take up to a minute.
              </p>
            </div>
          )}

          {/* Logged in, site check failed for a reason that isn't "no site yet" */}
          {user && !siteLoading && siteError && (
            <div className="max-w-md mx-auto bg-red-50 border border-red-200 rounded-lg p-6 text-center">
              <p className="text-red-800 font-medium">Could not load your site</p>
              <p className="text-red-700 text-sm mt-2">{siteError}</p>
              <button
                onClick={retrySite}
                className="mt-4 bg-red-600 text-white py-2 px-5 rounded-md font-medium hover:bg-red-700"
              >
                Try again
              </button>
            </div>
          )}

          {/* Logged in, no site → setup wizard */}
          {user && !siteLoading && !site && !siteError && (
            <SetupWizard onComplete={handleSetupComplete} />
          )}

          {/* Logged in, has site → dashboard */}
          {user && !siteLoading && site && (
            <>
              <div className="flex items-center justify-between mb-6">
                <p className="text-sm text-gray-600">Signed in as <span className="font-medium">{user?.email}</span></p>
                <div className="flex items-center gap-4">
                  <a href="/settings" className="text-sm text-blue-600 hover:text-blue-800">Settings</a>
                  <button onClick={handleLogout} className="text-sm text-red-600 hover:text-red-800">Sign out</button>
                </div>
              </div>

              {/* Run controls. Battery config (capacity, power limits, SOC bounds)
                  lives in Settings; the backend reads it, so there is nothing to
                  configure here — only "where is the battery right now", which it
                  cannot know without live data. */}
              <div className="flex flex-wrap items-center justify-between gap-4 mb-6 bg-white rounded-lg shadow px-4 py-3">
                  <div className="text-sm text-gray-600">
                    {hasLiveSoc ? (
                      <span>
                        Live SOC <span className="font-medium text-gray-900">{formatNumber(realtimeData.soc_pct, 0)}%</span>
                      </span>
                    ) : (
                      <span className="text-gray-500">Live SOC unavailable</span>
                    )}
                    {lastRunAt && <span className="text-gray-400"> · optimised {lastRunAt}</span>}
                  </div>
                  <div className="flex items-center gap-3">
                    {!hasLiveSoc && (
                      <label className="text-sm text-gray-600 flex items-center gap-2">
                        Initial SOC %
                        <input
                          type="number"
                          min={0}
                          max={100}
                          value={manualSoc}
                          onChange={(e) => setManualSoc(e.target.value)}
                          placeholder="50"
                          className="w-20 px-2 py-1 border border-gray-300 rounded-md text-sm focus:ring-blue-500 focus:border-blue-500"
                        />
                      </label>
                    )}
                    <button
                      onClick={runOptimiser}
                      disabled={loading || (!hasLiveSoc && manualSoc === '')}
                      title={!hasLiveSoc && manualSoc === '' ? 'Enter an initial SOC % first' : undefined}
                      className="bg-blue-600 text-white py-2 px-5 rounded-md font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {loading ? 'Optimising…' : schedule ? 'Re-run optimiser' : 'Run optimiser'}
                    </button>
                  </div>
                </div>

                <div>
                  {realtimeData.error && (
                    <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 mb-6">
                      <p className="text-yellow-800"><strong>Live battery data unavailable:</strong> {realtimeData.error}</p>
                      <p className="text-yellow-700 text-sm mt-1">Set an initial SOC above and run the optimiser manually.</p>
                    </div>
                  )}

                  {error === 'no_data' ? (
                    <div className="bg-amber-50 border border-amber-200 rounded-lg p-6 mb-6">
                      <h3 className="text-amber-800 font-semibold mb-2">No forecast data yet</h3>
                      <p className="text-amber-700 mb-3">
                        We need your solar forecast and energy usage data to generate an optimisation schedule.
                      </p>
                      <p className="text-amber-600 text-sm mb-3">
                        Make sure your Solcast API key, Solcast PV System ID, and FoxESS API key are configured.
                        Data is fetched daily by our background services — it may take up to 24 hours after first setup.
                      </p>
                      <a href="/settings" className="text-sm font-medium text-amber-700 underline hover:text-amber-900">
                        Configure API credentials →
                      </a>
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
                      {IS_DEV && (
                        <div className="flex items-center gap-2 mb-4">
                          <label className="text-sm text-gray-600 flex items-center gap-2 cursor-pointer select-none">
                            <input
                              type="checkbox"
                              checked={showEstimated}
                              onChange={(e) => setShowEstimated(e.target.checked)}
                              className="h-4 w-4 text-blue-600 focus:ring-blue-500"
                            />
                            Show estimated tail (backfilled prices — test only)
                          </label>
                        </div>
                      )}
                      <ScheduleCharts schedule={schedule} historicData={realtimeData.history} nowTime={realtimeData.fetchedAt} dayPrices={dayPrices} showEstimated={showEstimated} />

                      {/* Push to Inverter */}
                      <div className="bg-white rounded-lg shadow p-6 mt-6">
                        <div className="flex items-center justify-between">
                          <div>
                            <h3 className="font-semibold text-gray-900">Push to Inverter</h3>
                            <p className="text-sm text-gray-500 mt-1">
                              Preview the instructions, then send this optimised schedule to your FoxESS inverter. The schedule will be active until the next push or until you change it manually.
                            </p>
                          </div>
                          <div className="flex items-center gap-2 ml-4 whitespace-nowrap">
                            <button
                              onClick={handlePreview}
                              disabled={previewing || pushing}
                              className="bg-blue-600 text-white py-2 px-5 rounded-md font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                              {previewing ? 'Previewing...' : 'Preview'}
                            </button>
                            <button
                              onClick={handlePush}
                              disabled={pushing || previewing}
                              className="bg-green-600 text-white py-2 px-6 rounded-md font-medium hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                              {pushing ? 'Pushing...' : 'Push now'}
                            </button>
                          </div>
                        </div>

                        {/* Preview instructions */}
                        {previewResult && (
                          <div className="mt-4">
                            <p className={`text-sm font-medium ${previewResult.success ? 'text-blue-700' : 'text-red-700'}`}>
{previewResult.success
                              ? `Preview: ${previewResult.schedule.length} instruction(s) to push (SOC ${previewResult.soc}%) — times in Europe/London${previewResult.remainMode ? ` · remain mode: ${previewResult.remainMode}` : ''}`
                              : `Error: ${previewResult.error}`}
                            </p>
                            {previewResult.success && previewResult.schedule.length > 0 && (
                              <div className="mt-2 overflow-x-auto">
                                <table className="text-xs w-full">
                                  <thead>
                                    <tr className="border-b border-gray-200">
                                      <th className="text-left py-1 pr-3 text-gray-500 font-medium">Time</th>
                                      <th className="text-left py-1 pr-3 text-gray-500 font-medium">Mode</th>
                                      <th className="text-left py-1 text-gray-500 font-medium">Details</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {previewResult.schedule.map((g, i) => (
                                      <tr key={i} className="border-b border-gray-100">
                                        <td className="py-1 pr-3 font-mono text-gray-700">{g.start}–{g.end}</td>
                                        <td className="py-1 pr-3">
                                          <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${
                                            g.mode === 'ForceCharge' ? 'bg-blue-100 text-blue-800' :
                                            g.mode === 'ForceDischarge' ? 'bg-orange-100 text-orange-800' :
                                            g.mode === 'Feedin' ? 'bg-green-100 text-green-800' :
                                            'bg-gray-100 text-gray-800'
                                          }`}>
                                            {g.mode}
                                          </span>
                                        </td>
                                        <td className="py-1 text-gray-500">{g.description}</td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              </div>
                            )}
                          </div>
                        )}

                        {pushResult && (
                          <div className="mt-3">
                            <p className={`text-sm font-medium ${pushResult.success ? 'text-green-700' : 'text-red-700'}`}>
                              {pushResult.success
                                ? `Sent ${pushResult.groups} groups to inverter (SOC ${pushResult.soc}%)`
                                : `Error: ${pushResult.error}`}
                            </p>
                            {pushResult.success && pushResult.schedule.length > 0 && (
                              <div className="mt-3 overflow-x-auto">
                                <table className="text-xs w-full">
                                  <thead>
                                    <tr className="border-b border-gray-200">
                                      <th className="text-left py-1 pr-3 text-gray-500 font-medium">Time</th>
                                      <th className="text-left py-1 pr-3 text-gray-500 font-medium">Mode</th>
                                      <th className="text-left py-1 text-gray-500 font-medium">Details</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {pushResult.schedule.map((g, i) => (
                                      <tr key={i} className="border-b border-gray-100">
                                        <td className="py-1 pr-3 font-mono text-gray-700">{g.start}–{g.end}</td>
                                        <td className="py-1 pr-3">
                                          <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${
                                            g.mode === 'ForceCharge' ? 'bg-blue-100 text-blue-800' :
                                            g.mode === 'ForceDischarge' ? 'bg-orange-100 text-orange-800' :
                                            g.mode === 'Feedin' ? 'bg-green-100 text-green-800' :
                                            'bg-gray-100 text-gray-800'
                                          }`}>
                                            {g.mode}
                                          </span>
                                        </td>
                                        <td className="py-1 text-gray-500">{g.description}</td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    </>
                  )}

                  {!schedule && !loading && !error && (
                    <div className="bg-white rounded-lg shadow p-12 text-center">
                      <p className="text-gray-500 text-lg">
                        {hasLiveSoc ? 'Optimising…' : 'Enter an initial SOC and run the optimiser to see the schedule'}
                      </p>
                    </div>
                  )}
                </div>
            </>
          )}
        </div>
      </main>
    </>
  )
}
