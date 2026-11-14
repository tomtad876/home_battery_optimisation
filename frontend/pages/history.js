import Head from 'next/head'
import { useState, useEffect, useCallback, useRef } from 'react'
import AuthForm from '@/components/AuthForm'
import CostHistoryChart from '@/components/CostHistoryChart'
import { supabase } from '@/lib/supabaseClient'
import { apiFetch, friendlyError } from '@/lib/api'

// Windows shown as headline cards. Server-side aggregates, so each card is the
// same arithmetic the API exposes — no client-side re-derivation of the layers.
const WINDOWS = [
  { key: 'today', label: 'Today', note: 'so far' },
  { key: '7d', label: 'This week', note: '7 days' },
  { key: '30d', label: 'This month', note: '30 days' },
  { key: '365d', label: 'This year', note: '365 days' },
  { key: 'all', label: 'All time', note: 'since install' },
]

const RANGES = [
  { key: '30', label: '30d' },
  { key: '90', label: '90d' },
  { key: '365', label: '1y' },
  { key: 'all', label: 'All' },
]

const money = (v) => {
  const n = Number(v || 0)
  return `${n < 0 ? '−' : ''}£${Math.abs(n).toFixed(2)}`
}

const pct = (part, whole) => (whole ? Math.round((part / whole) * 100) : 0)

function isoDaysAgo(days) {
  const d = new Date()
  d.setDate(d.getDate() - (days - 1))
  return d.toISOString().slice(0, 10)
}

/** The three-way split the page exists to show. */
function Attribution({ data, windowLabel }) {
  const solar = Number(data?.solar_value_gbp || 0)
  const battery = Number(data?.battery_value_gbp || 0)
  const optimiser = Number(data?.optimiser_value_gbp || 0)
  const total = Number(data?.total_value_gbp || 0)
  const positive = Math.max(solar, 0) + Math.max(battery, 0) + Math.max(optimiser, 0)

  const segment = (value, colour) => {
    const v = Math.max(value, 0)
    if (!positive || !v) return null
    return <div className={`h-full ${colour}`} style={{ width: `${(v / positive) * 100}%` }} />
  }

  return (
    <div className="bg-surface border border-hairline rounded-card shadow-card p-5">
      <div className="flex items-baseline justify-between mb-1">
        <h2 className="text-lg font-semibold text-ink">Where the saving came from</h2>
        <span className="text-sm text-ink-muted">{money(total)} · {windowLabel}</span>
      </div>
      <p className="text-xs text-ink-muted mb-4">
        Against buying every kWh from the grid at your import rate, plus standing charge.
        Percentages are each source&apos;s share of the total saving.
      </p>

      <div className="flex h-3 w-full overflow-hidden rounded-full bg-surface-2 border border-hairline mb-4">
        {segment(solar, 'bg-solar')}
        {segment(battery, 'bg-discharge')}
        {segment(optimiser, 'bg-signal')}
      </div>

      <dl className="grid grid-cols-3 gap-3 text-sm">
        <div>
          <dt className="flex items-center gap-2 text-ink-muted">
            <span className="w-2 h-2 rounded-full bg-solar" /> Solar
          </dt>
          <dd className="text-ink font-semibold mt-1">
            {money(solar)} <span className="text-ink-faint font-normal">{pct(solar, total)}%</span>
          </dd>
        </div>
        <div>
          <dt className="flex items-center gap-2 text-ink-muted">
            <span className="w-2 h-2 rounded-full bg-discharge" /> Battery
          </dt>
          <dd className="text-ink font-semibold mt-1">
            {money(battery)} <span className="text-ink-faint font-normal">{pct(battery, total)}%</span>
          </dd>
        </div>
        <div>
          <dt className="flex items-center gap-2 text-ink-muted">
            <span className="w-2 h-2 rounded-full bg-signal" /> Optimiser
          </dt>
          <dd className={`font-semibold mt-1 ${optimiser < 0 ? 'text-danger-ink' : 'text-ink'}`}>
            {money(optimiser)} <span className="text-ink-faint font-normal">{pct(optimiser, total)}%</span>
          </dd>
        </div>
      </dl>

      {optimiser < 0 && (
        <p className="text-xs text-danger-ink mt-3">
          The optimiser is currently behind the self-use baseline: moving the battery against prices has
          not yet paid for the forecast risk it takes on.
        </p>
      )}

      <p className="text-xs text-ink-faint mt-4 leading-relaxed">
        <strong className="text-ink-muted">Battery</strong> is what a self-use battery adds — charging only
        from surplus PV, never importing to charge, never exporting from the battery.
        <strong className="text-ink-muted"> Optimiser</strong> is what this app adds on top of that, by
        moving the battery against prices. It is measured against an idealised device, so it is a hard baseline.
      </p>
    </div>
  )
}

export default function History() {
  const [user, setUser] = useState(null)
  const [site, setSite] = useState(null)
  const [siteLoading, setSiteLoading] = useState(true)
  const [summaries, setSummaries] = useState({})
  const [daily, setDaily] = useState([])
  const [range, setRange] = useState('90')
  const [mode, setMode] = useState('daily')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const tokenRef = useRef(null)

  const loadSummary = useCallback(async (token) => {
    const results = await Promise.all(
      WINDOWS.map((w) =>
        apiFetch(`/history/summary?window=${w.key}`, { accessToken: token })
          .then((data) => [w.key, data])
          .catch(() => [w.key, null])
      )
    )
    setSummaries(Object.fromEntries(results))
  }, [])

  const loadDaily = useCallback(async (token, r) => {
    const to = new Date().toISOString().slice(0, 10)
    const from = r === 'all' ? '2020-01-01' : isoDaysAgo(Number(r))
    const data = await apiFetch(`/history/daily?from_date=${from}&to_date=${to}`, { accessToken: token })
    setDaily(data?.days || [])
  }, [])

  const loadAll = useCallback(
    async (token, r = range) => {
      setLoading(true)
      setError(null)
      try {
        await Promise.all([loadSummary(token), loadDaily(token, r)])
      } catch (err) {
        setError(friendlyError(err, 'Could not load your cost history.'))
      } finally {
        setLoading(false)
      }
    },
    [loadDaily, loadSummary, range]
  )

  useEffect(() => {
    let mounted = true
    let lastToken = null

    const applySession = (session) => {
      const token = session?.access_token ?? null
      if (token && token === lastToken) return
      lastToken = token
      tokenRef.current = token
      setUser(session?.user ?? null)
      if (!token) {
        setSite(null)
        setSiteLoading(false)
        return
      }
      setSiteLoading(true)
      apiFetch('/sites/me', { accessToken: token })
        .then((res) => {
          if (!mounted || token !== lastToken) return
          setSite(res?.site ?? null)
          return loadAll(token)
        })
        .catch((err) => {
          if (!mounted || token !== lastToken) return
          setError(friendlyError(err, 'Could not load your site.'))
        })
        .finally(() => mounted && setSiteLoading(false))
    }

    supabase.auth.getSession().then(({ data }) => applySession(data?.session ?? null))
    const { data: sub } = supabase.auth.onAuthStateChange((_event, session) => applySession(session))
    return () => {
      mounted = false
      sub?.subscription?.unsubscribe?.()
    }
  }, [loadAll])

  const changeRange = (r) => {
    setRange(r)
    const token = tokenRef.current
    if (!token) return
    setLoading(true)
    setError(null)
    loadDaily(token, r)
      .catch((err) => setError(friendlyError(err, 'Could not load that range.')))
      .finally(() => setLoading(false))
  }

  const handleLogout = async () => {
    await supabase.auth.signOut()
    setUser(null)
    setSite(null)
    setDaily([])
    setSummaries({})
  }

  const allTime = summaries.all
  const hasData = Number(allTime?.days || 0) > 0
  const coverage = allTime?.coverage_pct

  return (
    <>
      <Head>
        <title>Cost history · Battery optimiser</title>
      </Head>

      <main className="min-h-screen bg-canvas text-ink px-4 py-6">
        <div className="max-w-5xl mx-auto">
          <header className="flex items-center justify-between mb-8">
            <div>
              <h1 className="text-2xl font-bold">Cost history</h1>
              <p className="text-sm text-ink-muted">
                {site?.name ? `${site.name} — ` : ''}what the kit saved, and what did the saving
              </p>
            </div>
            <div className="flex items-center gap-4">
              <a href="/" className="text-sm text-ink-muted hover:text-ink">Dashboard</a>
              <a href="/events" className="text-sm text-ink-muted hover:text-ink">Events</a>
              <a href="/settings" className="text-sm text-ink-muted hover:text-ink">Settings</a>
              {user && (
                <button onClick={handleLogout} className="text-sm text-danger-ink hover:brightness-110">
                  Sign out
                </button>
              )}
            </div>
          </header>

          {!user && !siteLoading && <AuthForm />}

          {user && siteLoading && <p className="text-ink-muted">Connecting…</p>}

          {error && (
            <div className="bg-danger-surface border border-danger-border rounded-card p-4 mb-6">
              <p className="text-danger-ink"><strong>Error:</strong> {error}</p>
            </div>
          )}

          {user && !siteLoading && !hasData && !loading && (
            <div className="bg-warn-surface border border-warn-border rounded-card p-6">
              <h2 className="text-warn-ink font-semibold mb-2">No cost history yet</h2>
              <p className="text-warn-ink text-sm">
                Cost history is built from your meter and inverter history. Once a few days of data have
                been collected, the daily summary appears here.
              </p>
            </div>
          )}

          {hasData && (
            <>
              {/* Headline cards */}
              <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-6">
                {WINDOWS.map((w) => {
                  const d = summaries[w.key]
                  const value = d?.total_value_gbp
                  return (
                    <div key={w.key} className="bg-surface border border-hairline rounded-card shadow-card p-4">
                      <p className="text-xs text-ink-muted">{w.label}</p>
                      <p className={`text-2xl font-bold mt-1 ${Number(value) < 0 ? 'text-danger-ink' : 'text-ink'}`}>
                        {value === undefined || value === null ? '—' : money(value)}
                      </p>
                      <p className="text-xs text-ink-faint mt-1">
                        {w.note}
                        {w.key === 'today' && d?.coverage_pct != null ? ` · ${d.coverage_pct}% of day` : ''}
                      </p>
                    </div>
                  )
                })}
              </div>

              <div className="grid md:grid-cols-2 gap-4 mb-6">
                <Attribution data={summaries['30d'] || allTime} windowLabel="last 30 days" />
                <div className="bg-surface border border-hairline rounded-card shadow-card p-5">
                  <h2 className="text-lg font-semibold mb-1">Energy and money, all time</h2>
                  <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm mt-3">
                    <dt className="text-ink-muted">Imported</dt>
                    <dd className="text-ink text-right">{Number(allTime?.import_kwh || 0).toFixed(0)} kWh</dd>
                    <dt className="text-ink-muted">Exported</dt>
                    <dd className="text-ink text-right">{Number(allTime?.export_kwh || 0).toFixed(0)} kWh</dd>
                    <dt className="text-ink-muted">Solar generated</dt>
                    <dd className="text-ink text-right">{Number(allTime?.pv_kwh || 0).toFixed(0)} kWh</dd>
                    <dt className="text-ink-muted">House used</dt>
                    <dd className="text-ink text-right">{Number(allTime?.load_kwh || 0).toFixed(0)} kWh</dd>
                    <dt className="text-ink-muted pt-2 border-t border-hairline">Import cost</dt>
                    <dd className="text-ink text-right pt-2 border-t border-hairline">{money(allTime?.import_cost_gbp)}</dd>
                    <dt className="text-ink-muted">Export income</dt>
                    <dd className="text-gridout text-right">{money(allTime?.export_income_gbp)}</dd>
                    <dt className="text-ink-muted">Standing charges</dt>
                    <dd className="text-ink text-right">{money(allTime?.standing_gbp)}</dd>
                    <dt className="text-ink-muted font-medium">Net energy cost</dt>
                    <dd className={`text-right font-semibold ${Number(allTime?.net_cost_gbp) < 0 ? 'text-gridout' : 'text-ink'}`}>
                      {money(allTime?.net_cost_gbp)}
                    </dd>
                  </dl>
                </div>
              </div>

              {/* Chart */}
              <div className="bg-surface border border-hairline rounded-card shadow-card p-5 mb-4">
                <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
                  <h2 className="text-lg font-semibold">Daily cost</h2>
                  <div className="flex items-center gap-2">
                    <div className="flex rounded-full border border-hairline overflow-hidden">
                      {RANGES.map((r) => (
                        <button
                          key={r.key}
                          onClick={() => changeRange(r.key)}
                          className={`px-3 py-1 text-xs ${range === r.key ? 'bg-signal/15 text-signal' : 'text-ink-muted hover:text-ink'}`}
                        >
                          {r.label}
                        </button>
                      ))}
                    </div>
                    <div className="flex rounded-full border border-hairline overflow-hidden">
                      {['daily', 'cumulative'].map((m) => (
                        <button
                          key={m}
                          onClick={() => setMode(m)}
                          className={`px-3 py-1 text-xs capitalize ${mode === m ? 'bg-signal/15 text-signal' : 'text-ink-muted hover:text-ink'}`}
                        >
                          {m}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
                {loading && daily.length === 0 ? (
                  <p className="text-ink-muted text-sm">Loading…</p>
                ) : (
                  <CostHistoryChart days={daily} mode={mode} />
                )}
              </div>

              <p className="text-xs text-ink-faint leading-relaxed">
                {allTime?.days} days of history ({allTime?.first_day} → {allTime?.last_day}),{' '}
                {coverage != null ? `${coverage}% of half-hours covered` : 'coverage unknown'}.
                Money is inc VAT, priced at the tariff in force each day.
                Import and export come from your{' '}
                {allTime?.source?.includes('octopus') ? 'supplier meter' : 'inverter (no Octopus connection)'}.
                Days with missing readings are included as-is and will understate savings slightly.
              </p>
            </>
          )}
        </div>
      </main>
    </>
  )
}
