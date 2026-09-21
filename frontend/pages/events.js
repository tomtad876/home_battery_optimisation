import Head from 'next/head'
import { useState, useEffect, useCallback } from 'react'
import {
  Chart as ChartJS, CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Filler,
} from 'chart.js'
import { Line } from 'react-chartjs-2'
import AuthForm from '@/components/AuthForm'
import { supabase } from '@/lib/supabaseClient'
import { apiFetch, friendlyError } from '@/lib/api'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Filler)

// The Cosy and the heating are two modes of the same heat pump (mutually
// exclusive), so the labels name the mode, not a separate device.
const APPLIANCES = [
  'cosy', 'heating', 'hob', 'oven', 'airfryer', 'cooking',
  'washing_machine', 'tumble_dryer', 'dishwasher', 'gaming', 'combined', 'other',
]

const APPLIANCE_LABELS = {
  cosy: 'Cosy (heat pump · hot water)',
  heating: 'Heating (heat pump · radiators)',
  hob: 'Hob',
  oven: 'Oven',
  airfryer: 'Air fryer',
  cooking: 'Cooking (unsure which)',
  washing_machine: 'Washing machine',
  tumble_dryer: 'Tumble dryer',
  dishwasher: 'Dishwasher',
  gaming: 'Gaming / PC',
  combined: 'Multiple / combined',
  other: 'Other',
  not_appliance: 'Not an appliance',
}

// Cooking sub-classes where the meter can't reliably tell them apart.
const AMBIGUOUS_COOKING = ['hob', 'airfryer', 'cooking']

// Cleanliness is the primary filter for template fitting: signatures must be
// fit on isolated examples only.
const CLEANLINESS = [
  { value: 'clean', label: '✓ Clean isolated', on: 'bg-green-600 text-white border-green-600' },
  { value: 'unsure', label: '? Not sure', on: 'bg-amber-500 text-white border-amber-500' },
  { value: 'contaminated', label: '⚠ Others running', on: 'bg-red-600 text-white border-red-600' },
]

const cleanLabel = (v) => CLEANLINESS.find((c) => c.value === v)?.label || 'Not annotated'

const RECENT_DAYS = 14

// Local (Europe/London) calendar day key 'YYYY-MM-DD' — matches the inventory API.
function dayKey(value) {
  return new Date(value).toLocaleDateString('en-CA', { timeZone: 'Europe/London' })
}

function recentDayKeys(n) {
  const keys = []
  const now = Date.now()
  for (let i = 0; i < n; i += 1) keys.push(dayKey(now - i * 86400000))
  return keys
}

function dayLabel(key) {
  return new Date(`${key}T12:00:00Z`).toLocaleDateString('en-GB', {
    weekday: 'short', day: 'numeric', month: 'short', timeZone: 'Europe/London',
  })
}

function Sparkline({ trace }) {
  if (!trace || trace.length < 2) return null
  const labels = trace.map((p) =>
    new Date(p.t).toLocaleTimeString('en-GB', {
      hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Europe/London',
    })
  )
  const data = {
    labels,
    datasets: [{
      label: 'kW',
      data: trace.map((p) => p.kw),
      borderColor: '#6366F1',
      backgroundColor: 'rgba(99,102,241,0.08)',
      borderWidth: 1.5,
      pointRadius: 0,
      tension: 0.25,
      fill: true,
    }],
  }
  const options = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { display: false }, tooltip: { enabled: false } },
    scales: { x: { display: false }, y: { display: false } },
  }
  return <div style={{ height: 48 }}><Line data={data} options={options} /></div>
}

function CleanlinessControl({ value, onChange }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {CLEANLINESS.map((c) => (
        <button
          key={c.value}
          type="button"
          onClick={() => onChange(c.value)}
          aria-pressed={value === c.value}
          className={`px-2.5 py-1 rounded-md text-xs font-medium border ${
            value === c.value ? c.on : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-100'
          }`}
        >
          {c.label}
        </button>
      ))}
    </div>
  )
}

export default function Events() {
  const [user, setUser] = useState(null)
  const [site, setSite] = useState(null)
  const [siteLoading, setSiteLoading] = useState(true)
  const [siteError, setSiteError] = useState(null)
  const [tab, setTab] = useState('review')
  const [candidates, setCandidates] = useState([])
  const [labelled, setLabelled] = useState([])
  const [inventory, setInventory] = useState({}) // day -> { appliances, notes }
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [busyKey, setBusyKey] = useState(null)

  // Log form state
  const [log, setLog] = useState({
    appliance: 'cosy', startLocal: '', durationMin: '', status: 'confirmed',
    energyKwh: '', cleanliness: 'clean', targetTemp: '',
  })
  const [logSubmitting, setLogSubmitting] = useState(false)
  const [logMessage, setLogMessage] = useState(null)

  const loadData = useCallback(async (accessToken) => {
    setLoading(true)
    setError(null)
    try {
      const [detected, existing, inv] = await Promise.all([
        apiFetch('/events/detect?days=7', { accessToken }),
        apiFetch('/events', { accessToken }),
        apiFetch(`/events/inventory?days=${RECENT_DAYS}`, { accessToken }),
      ])
      // Give every candidate editable annotation state up front.
      setCandidates((detected?.events || []).map((c) => ({
        ...c,
        appliance: c.suggested_appliance,
        cleanliness: 'unsure',
        targetTemp: '',
        startTemp: '',
        notes: '',
        splitMode: false,
        splitAppliance: '',
      })))
      setLabelled(existing?.events || [])
      const invMap = {}
      for (const row of inv?.days || []) invMap[row.day] = row
      setInventory(invMap)
    } catch (err) {
      setError(friendlyError(err, 'Could not load events.'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    let mounted = true
    let lastToken = null

    // One session handler for both the initial getSession() and the auth
    // listener. Previously the listener only called loadData() — it never
    // fetched /sites/me nor cleared siteLoading, so a SIGNED_IN fired on load
    // (or by signing in on this page) left the UI stuck on "Connecting…".
    // Dedupe on the access token so the getSession + listener double-fire on
    // mount doesn't fetch everything twice.
    const applySession = (session) => {
      const token = session?.access_token ?? null
      if (token && token === lastToken) return
      lastToken = token

      setUser(session?.user ?? null)
      setSiteError(null)
      if (!token) {
        setSite(null)
        setSiteLoading(false)
        return
      }
      setSiteLoading(true)
      apiFetch('/sites/me', { accessToken: token })
        .then((res) => {
          if (!mounted) return
          setSite(res?.site ?? null)
          return loadData(token)
        })
        .catch((err) => {
          if (!mounted) return
          if (err?.status !== 404) setSiteError(friendlyError(err, 'Could not load your site.'))
          setSite(null)
        })
        .finally(() => { if (mounted) setSiteLoading(false) })
    }

    supabase.auth.getSession().then(({ data }) => {
      if (mounted) applySession(data?.session ?? null)
    })

    const { data: listener } = supabase.auth.onAuthStateChange((event, session) => {
      if (!mounted) return
      if (event === 'SIGNED_IN' || event === 'INITIAL_SESSION') {
        applySession(session ?? null)
      } else if (event === 'SIGNED_OUT') {
        lastToken = null
        setUser(null)
        setSite(null)
        setCandidates([])
        setLabelled([])
        setInventory({})
        setSiteLoading(false)
      }
    })

    return () => {
      mounted = false
      listener?.subscription?.unsubscribe?.()
    }
  }, [loadData])

  const getToken = async () => (await supabase.auth.getSession()).data?.session?.access_token

  const patchCandidate = (key, patch) => {
    setCandidates((prev) => prev.map((c) => (c.start_time === key ? { ...c, ...patch } : c)))
  }

  // Build the POST body shared by confirm/log — blank numerics omitted so the
  // backend stores NULL rather than 0.
  const eventBody = (c, overrides = {}) => {
    const body = {
      appliance: c.appliance,
      start_time: c.start_time,
      end_time: c.end_time,
      status: 'confirmed',
      source: 'review',
      cleanliness: c.cleanliness,
      notes: c.notes || null,
    }
    const target = Number(c.targetTemp)
    if (c.targetTemp !== '' && !Number.isNaN(target)) body.target_temp = target
    const start = Number(c.startTemp)
    if (c.startTemp !== '' && !Number.isNaN(start)) body.start_temp = start
    return { ...body, ...overrides }
  }

  const refreshLabelled = async (accessToken) => {
    const existing = await apiFetch('/events', { accessToken })
    setLabelled(existing?.events || [])
  }

  const confirmCandidate = async (candidate) => {
    setBusyKey(candidate.start_time)
    try {
      const accessToken = await getToken()
      await apiFetch('/events', { method: 'POST', accessToken, body: eventBody(candidate) })
      setCandidates((prev) => prev.filter((c) => c.start_time !== candidate.start_time))
      await refreshLabelled(accessToken)
    } catch (err) {
      setError(friendlyError(err, 'Could not save the label.'))
    } finally {
      setBusyKey(null)
    }
  }

  // A window that is genuinely two appliances becomes two overlapping rows.
  const splitCandidate = async (candidate) => {
    if (!candidate.splitAppliance) {
      setError('Pick the second appliance before saving the split.')
      return
    }
    setBusyKey(candidate.start_time)
    try {
      const accessToken = await getToken()
      await apiFetch('/events', {
        method: 'POST', accessToken,
        body: eventBody(candidate, { cleanliness: 'contaminated' }),
      })
      await apiFetch('/events', {
        method: 'POST', accessToken,
        body: eventBody(candidate, {
          appliance: candidate.splitAppliance,
          cleanliness: 'contaminated',
          notes: candidate.notes || null,
        }),
      })
      setCandidates((prev) => prev.filter((c) => c.start_time !== candidate.start_time))
      await refreshLabelled(accessToken)
    } catch (err) {
      setError(friendlyError(err, 'Could not save the split.'))
    } finally {
      setBusyKey(null)
    }
  }

  const rejectCandidate = async (candidate) => {
    setBusyKey(candidate.start_time)
    try {
      const accessToken = await getToken()
      await apiFetch('/events', {
        method: 'POST', accessToken,
        body: {
          appliance: 'not_appliance',
          start_time: candidate.start_time,
          end_time: candidate.end_time,
          status: 'confirmed',
          source: 'review',
        },
      })
      setCandidates((prev) => prev.filter((c) => c.start_time !== candidate.start_time))
      await refreshLabelled(accessToken)
    } catch (err) {
      setError(friendlyError(err, 'Could not save the label.'))
    } finally {
      setBusyKey(null)
    }
  }

  const deleteEvent = async (id) => {
    try {
      const accessToken = await getToken()
      await apiFetch(`/events/${id}`, { method: 'DELETE', accessToken })
      setLabelled((prev) => prev.filter((e) => e.id !== id))
    } catch (err) {
      setError(friendlyError(err, 'Could not delete the event.'))
    }
  }

  const patchEvent = async (id, body) => {
    const accessToken = await getToken()
    const res = await apiFetch(`/events/${id}`, { method: 'PATCH', accessToken, body })
    setLabelled((prev) => prev.map((e) => (e.id === id ? (res?.event ?? { ...e, ...body }) : e)))
  }

  const saveInventory = async (day, appliances, notes) => {
    const accessToken = await getToken()
    const res = await apiFetch(`/events/inventory/${day}`, {
      method: 'PUT', accessToken, body: { appliances, notes: notes || null },
    })
    setInventory((prev) => ({ ...prev, [day]: res?.day ?? { day, appliances, notes } }))
  }

  const submitLog = async () => {
    if (!log.startLocal) {
      setLogMessage({ ok: false, text: 'Set a start time.' })
      return
    }
    setLogSubmitting(true)
    setLogMessage(null)
    try {
      const accessToken = await getToken()
      const start = new Date(log.startLocal).toISOString()
      const dur = Number(log.durationMin)
      const end = dur > 0
        ? new Date(new Date(log.startLocal).getTime() + dur * 60000).toISOString()
        : null
      const body = {
        appliance: log.appliance,
        start_time: start,
        end_time: end,
        status: log.status,
        energy_kwh: log.energyKwh === '' ? null : Number(log.energyKwh),
        source: 'manual',
        cleanliness: log.cleanliness,
      }
      const target = Number(log.targetTemp)
      if (log.targetTemp !== '' && !Number.isNaN(target)) body.target_temp = target
      await apiFetch('/events', { method: 'POST', accessToken, body })
      setLog({ appliance: 'cosy', startLocal: '', durationMin: '', status: 'confirmed', energyKwh: '', cleanliness: 'clean', targetTemp: '' })
      setLogMessage({ ok: true, text: 'Logged.' })
      await refreshLabelled(accessToken)
    } catch (err) {
      setLogMessage({ ok: false, text: friendlyError(err, 'Could not log the event.') })
    } finally {
      setLogSubmitting(false)
    }
  }

  const handleLogout = async () => { await supabase.auth.signOut() }

  // Group candidates by day (newest first).
  const grouped = {}
  for (const c of candidates) {
    const day = c.start_local.slice(0, 10)
    ;(grouped[day] ||= []).push(c)
  }
  const days = Object.keys(grouped).sort().reverse()

  const needsReview = candidates.length

  return (
    <>
      <Head>
        <title>Demand Events</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
      </Head>
      <main className="min-h-screen bg-gray-50">
        <div className="max-w-5xl mx-auto py-12 px-4">
          <header className="mb-8">
            <h1 className="text-3xl font-bold text-gray-900">Demand Events</h1>
            <p className="text-gray-600 mt-2">
              Label the appliances behind your demand spikes so the forecast learns your routine.
            </p>
          </header>

          {!user && (
            <div className="max-w-md mx-auto">
              <AuthForm onLogin={() => supabase.auth.getSession().then(({ data }) => setUser(data?.session?.user))} />
            </div>
          )}

          {user && siteLoading && <p className="text-center text-gray-500 py-12">Connecting…</p>}

          {user && !siteLoading && siteError && (
            <div className="max-w-md mx-auto bg-red-50 border border-red-200 rounded-lg p-6 text-center">
              <p className="text-red-800 font-medium">Could not load your site</p>
              <p className="text-red-700 text-sm mt-2">{siteError}</p>
            </div>
          )}

          {user && !siteLoading && !site && !siteError && (
            <div className="bg-amber-50 border border-amber-200 rounded-lg p-6 text-center">
              <p className="text-amber-800">Set up your site on the dashboard first.</p>
              <a href="/" className="text-amber-700 underline text-sm mt-2 inline-block">Go to dashboard →</a>
            </div>
          )}

          {user && !siteLoading && site && (
            <>
              <div className="flex items-center justify-between mb-6">
                <p className="text-sm text-gray-600">Signed in as <span className="font-medium">{user?.email}</span></p>
                <div className="flex items-center gap-4">
                  <a href="/" className="text-sm text-blue-600 hover:text-blue-800">Dashboard</a>
                  <a href="/settings" className="text-sm text-blue-600 hover:text-blue-800">Settings</a>
                  <button onClick={handleLogout} className="text-sm text-red-600 hover:text-red-800">Sign out</button>
                </div>
              </div>

              {/* Tabs */}
              <div className="flex gap-2 mb-6">
                <TabButton active={tab === 'review'} onClick={() => setTab('review')}>
                  Review {needsReview > 0 && <span className="ml-1 bg-white/20 rounded-full px-2 py-0.5 text-xs">{needsReview}</span>}
                </TabButton>
                <TabButton active={tab === 'daily'} onClick={() => setTab('daily')}>Daily</TabButton>
                <TabButton active={tab === 'log'} onClick={() => setTab('log')}>Log event</TabButton>
              </div>

              {error && (
                <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-6 flex items-start justify-between gap-4">
                  <p className="text-red-800 text-sm">{error}</p>
                  <button onClick={() => setError(null)} className="text-red-500 text-sm">dismiss</button>
                </div>
              )}

              {tab === 'review' && (
                <ReviewTab
                  days={days}
                  grouped={grouped}
                  loading={loading}
                  candidates={candidates}
                  labelled={labelled}
                  busyKey={busyKey}
                  patchCandidate={patchCandidate}
                  confirmCandidate={confirmCandidate}
                  splitCandidate={splitCandidate}
                  rejectCandidate={rejectCandidate}
                  deleteEvent={deleteEvent}
                  patchEvent={patchEvent}
                />
              )}

              {tab === 'daily' && (
                <DailyTab
                  labelled={labelled}
                  candidates={candidates}
                  inventory={inventory}
                  onSave={saveInventory}
                  onError={(msg) => setError(msg)}
                />
              )}

              {tab === 'log' && (
                <LogTab
                  log={log}
                  setLog={setLog}
                  logSubmitting={logSubmitting}
                  logMessage={logMessage}
                  submitLog={submitLog}
                />
              )}
            </>
          )}
        </div>
      </main>
    </>
  )
}

function TabButton({ active, onClick, children }) {
  return (
    <button
      onClick={onClick}
      className={`px-4 py-2 rounded-md font-medium text-sm ${
        active ? 'bg-blue-600 text-white' : 'bg-white text-gray-700 hover:bg-gray-100 border border-gray-300'
      }`}
    >
      {children}
    </button>
  )
}

function ReviewTab({
  days, grouped, loading, candidates, labelled, busyKey,
  patchCandidate, confirmCandidate, splitCandidate, rejectCandidate, deleteEvent, patchEvent,
}) {
  return (
    <div className="space-y-8">
      <p className="text-sm text-gray-500">
        Mark each window <span className="font-medium">clean isolated</span> only if nothing else was
        running — templates are fit from clean examples, so a contaminated label is worse than none.
      </p>

      {loading && candidates.length === 0 && (
        <p className="text-center text-gray-500 py-8">Detecting events…</p>
      )}

      {!loading && candidates.length === 0 && (
        <div className="bg-white rounded-lg shadow p-8 text-center">
          <p className="text-gray-700 font-medium">Nothing to review 🎉</p>
          <p className="text-gray-500 text-sm mt-2">
            Every detected event is already labelled. New events will appear here as they happen.
          </p>
        </div>
      )}

      {days.map((day) => (
        <div key={day}>
          <h3 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">{day}</h3>
          <div className="space-y-3">
            {grouped[day].map((c) => {
              const busy = busyKey === c.start_time
              return (
                <div key={c.start_time} className="bg-white rounded-lg shadow p-4" data-candidate={c.start_time}>
                  <div className="flex items-start gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-sm font-medium text-gray-900">
                          {c.start_local.slice(11)}–{c.end_local}
                        </span>
                        <span className="text-xs text-gray-400">
                          {c.dur_min} min · {c.peak_kw} kW peak · {c.energy_kwh} kWh
                        </span>
                        {c.cleanliness !== 'unsure' && (
                          <span className="text-xs font-medium text-gray-500">{cleanLabel(c.cleanliness)}</span>
                        )}
                      </div>
                      <div className="mt-1 text-xs text-gray-400">
                        detected as “{APPLIANCE_LABELS[c.suggested_appliance] || c.suggested_appliance}” ({c.confidence >= 0.7 ? 'confident' : 'guess'}, flatness {c.flatness})
                      </div>
                    </div>
                    <div className="w-40 shrink-0">
                      <Sparkline trace={c.trace} />
                    </div>
                  </div>

                  <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div>
                      <label className="block text-xs font-medium text-gray-500 mb-1">Appliance</label>
                      <select
                        value={c.appliance}
                        onChange={(e) => patchCandidate(c.start_time, { appliance: e.target.value })}
                        className="w-full px-2 py-1.5 border border-gray-300 rounded-md text-sm"
                      >
                        {APPLIANCES.map((a) => (
                          <option key={a} value={a}>{APPLIANCE_LABELS[a] || a}</option>
                        ))}
                      </select>
                    </div>
                    {c.appliance === 'cosy' && (
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">Cosy target temp</label>
                        <select
                          value={c.targetTemp}
                          onChange={(e) => patchCandidate(c.start_time, { targetTemp: e.target.value })}
                          className="w-full px-2 py-1.5 border border-gray-300 rounded-md text-sm"
                        >
                          <option value="">—</option>
                          <option value="50">50°C</option>
                          <option value="60">60°C</option>
                        </select>
                      </div>
                    )}
                  </div>

                  {AMBIGUOUS_COOKING.includes(c.appliance) && (
                    <p className="mt-2 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1">
                      An air fryer and a single hob ring look almost identical on the meter — check the Daily tab if you&rsquo;re not sure.
                    </p>
                  )}

                  <div className="mt-3">
                    <label className="block text-xs font-medium text-gray-500 mb-1">Was anything else running?</label>
                    <CleanlinessControl
                      value={c.cleanliness}
                      onChange={(v) => patchCandidate(c.start_time, { cleanliness: v })}
                    />
                  </div>

                  <div className="mt-3">
                    <input
                      type="text"
                      placeholder="Notes (optional) — e.g. tank start 42°C"
                      value={c.notes}
                      onChange={(e) => patchCandidate(c.start_time, { notes: e.target.value })}
                      className="w-full px-2 py-1.5 border border-gray-300 rounded-md text-sm"
                    />
                  </div>

                  {c.splitMode && (
                    <div className="mt-3 flex items-center gap-2">
                      <label className="text-xs font-medium text-gray-500">Second appliance</label>
                      <select
                        value={c.splitAppliance}
                        onChange={(e) => patchCandidate(c.start_time, { splitAppliance: e.target.value })}
                        className="px-2 py-1.5 border border-gray-300 rounded-md text-sm"
                      >
                        <option value="">pick…</option>
                        {APPLIANCES.map((a) => (
                          <option key={a} value={a}>{APPLIANCE_LABELS[a] || a}</option>
                        ))}
                      </select>
                    </div>
                  )}

                  <div className="mt-3 flex items-center gap-2 flex-wrap">
                    <button
                      onClick={() => confirmCandidate(c)}
                      disabled={busy}
                      className="px-3 py-1.5 rounded-md text-sm font-medium bg-green-600 text-white hover:bg-green-700 disabled:opacity-50"
                    >
                      ✓ Confirm
                    </button>
                    {c.splitMode ? (
                      <>
                        <button
                          onClick={() => splitCandidate(c)}
                          disabled={busy || !c.splitAppliance}
                          className="px-3 py-1.5 rounded-md text-sm font-medium bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
                        >
                          Save split
                        </button>
                        <button
                          onClick={() => patchCandidate(c.start_time, { splitMode: false, splitAppliance: '' })}
                          className="text-sm text-gray-500"
                        >
                          cancel
                        </button>
                      </>
                    ) : (
                      <button
                        onClick={() => patchCandidate(c.start_time, { splitMode: true })}
                        disabled={busy}
                        className="px-3 py-1.5 rounded-md text-sm font-medium bg-blue-100 text-blue-700 hover:bg-blue-200 disabled:opacity-50"
                      >
                        ＋ Split
                      </button>
                    )}
                    <button
                      onClick={() => rejectCandidate(c)}
                      disabled={busy}
                      className="px-3 py-1.5 rounded-md text-sm font-medium bg-gray-100 text-gray-600 hover:bg-gray-200 disabled:opacity-50"
                    >
                      ✗ Not an appliance
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      ))}

      {labelled.length > 0 && (
        <div className="pt-4 border-t border-gray-200">
          <h3 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">Labelled events ({labelled.length})</h3>
          <div className="space-y-2">
            {labelled.slice(0, 50).map((e) => (
              <LabelledEventRow key={e.id} event={e} onDelete={deleteEvent} onSave={patchEvent} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function LabelledEventRow({ event, onDelete, onSave }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(null)
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState(null)

  const when = new Date(event.start_time).toLocaleString('en-GB', {
    dateStyle: 'medium', timeStyle: 'short', timeZone: 'Europe/London',
  })

  const startEdit = () => {
    setDraft({
      appliance: event.appliance,
      cleanliness: event.cleanliness || 'unsure',
      targetTemp: event.target_temp ?? '',
      notes: event.notes || '',
    })
    setErr(null)
    setEditing(true)
  }

  const save = async () => {
    setSaving(true)
    setErr(null)
    try {
      await onSave(event.id, {
        appliance: draft.appliance,
        cleanliness: draft.cleanliness,
        target_temp: draft.targetTemp === '' ? null : Number(draft.targetTemp),
        notes: draft.notes || null,
      })
      setEditing(false)
    } catch (error) {
      setErr(friendlyError(error, 'Could not update the event.'))
    } finally {
      setSaving(false)
    }
  }

  if (!editing) {
    return (
      <div data-event={event.id} className="flex items-center justify-between bg-white rounded-lg shadow px-4 py-2">
        <div className="flex items-center gap-3 text-sm flex-wrap">
          <span className="font-medium text-gray-800">{APPLIANCE_LABELS[event.appliance] || event.appliance}</span>
          <span className="text-gray-500">{when}</span>
          {event.cleanliness && (
            <span className={`text-xs px-2 py-0.5 rounded-full ${
              event.cleanliness === 'clean' ? 'bg-green-100 text-green-800'
              : event.cleanliness === 'contaminated' ? 'bg-red-100 text-red-800'
              : 'bg-amber-100 text-amber-800'
            }`}>{cleanLabel(event.cleanliness)}</span>
          )}
          {event.target_temp != null && <span className="text-xs text-gray-500">{event.target_temp}°C</span>}
          <span className={`text-xs px-2 py-0.5 rounded-full ${
            event.status === 'confirmed' ? 'bg-green-100 text-green-800'
            : event.status === 'planned' ? 'bg-blue-100 text-blue-800'
            : 'bg-gray-100 text-gray-600'
          }`}>{event.status}</span>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          <button onClick={startEdit} data-edit className="text-sm text-blue-600 hover:text-blue-800">Edit</button>
          <button onClick={() => onDelete(event.id)} className="text-sm text-red-500 hover:text-red-700">Delete</button>
        </div>
      </div>
    )
  }

  return (
    <div data-event={event.id} className="bg-white rounded-lg shadow p-4 space-y-3 border border-blue-200">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-gray-700">{when}</span>
        <span className="text-xs text-gray-400">editing</span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Appliance</label>
          <select
            value={draft.appliance}
            onChange={(e) => setDraft((d) => ({ ...d, appliance: e.target.value }))}
            className="w-full px-2 py-1.5 border border-gray-300 rounded-md text-sm"
          >
            {APPLIANCES.map((a) => <option key={a} value={a}>{APPLIANCE_LABELS[a] || a}</option>)}
          </select>
        </div>
        {draft.appliance === 'cosy' && (
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Cosy target temp</label>
            <select
              value={draft.targetTemp}
              onChange={(e) => setDraft((d) => ({ ...d, targetTemp: e.target.value }))}
              className="w-full px-2 py-1.5 border border-gray-300 rounded-md text-sm"
            >
              <option value="">—</option>
              <option value="50">50°C</option>
              <option value="60">60°C</option>
            </select>
          </div>
        )}
      </div>
      <div>
        <label className="block text-xs font-medium text-gray-500 mb-1">Was anything else running?</label>
        <CleanlinessControl value={draft.cleanliness} onChange={(v) => setDraft((d) => ({ ...d, cleanliness: v }))} />
      </div>
      <input
        type="text"
        placeholder="Notes (optional)"
        value={draft.notes}
        onChange={(e) => setDraft((d) => ({ ...d, notes: e.target.value }))}
        className="w-full px-2 py-1.5 border border-gray-300 rounded-md text-sm"
      />
      <div className="flex items-center gap-2">
        <button
          onClick={save}
          disabled={saving}
          data-save
          className="px-3 py-1.5 rounded-md text-sm font-medium bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
        <button onClick={() => setEditing(false)} className="text-sm text-gray-500">Cancel</button>
      </div>
      {err && <p className="text-sm text-red-600">{err}</p>}
    </div>
  )
}

function DailyTab({ labelled, candidates, inventory, onSave, onError }) {
  // Union of appliances observed per local day, from labels + detections.
  const observed = {}
  const add = (day, appliance) => {
    if (!day || !appliance) return
    ;(observed[day] ||= new Set()).add(appliance)
  }
  for (const e of labelled) {
    if (e.appliance === 'not_appliance') continue
    add(dayKey(e.start_time), e.appliance)
  }
  for (const c of candidates) add(c.start_local.slice(0, 10), c.appliance)

  const days = recentDayKeys(RECENT_DAYS)

  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-500">
        Tick what actually ran each day. A day with a single appliance makes every detected window
        that day provably clean — so this is the cheapest way to grow the template data set.
      </p>
      {days.map((day) => (
        <DayCard
          key={day}
          day={day}
          observed={Array.from(observed[day] || [])}
          saved={inventory[day]}
          onSave={onSave}
          onError={onError}
        />
      ))}
    </div>
  )
}

function DayCard({ day, observed, saved, onSave, onError }) {
  const derived = observed
  const [selected, setSelected] = useState(saved ? saved.appliances : derived)
  const [notes, setNotes] = useState(saved?.notes || '')
  const [saving, setSaving] = useState(false)
  const [savedFlash, setSavedFlash] = useState(false)

  useEffect(() => {
    setSelected(saved ? saved.appliances : derived)
    setNotes(saved?.notes || '')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [saved, day])

  const toggle = (a) => {
    setSelected((prev) => (prev.includes(a) ? prev.filter((x) => x !== a) : [...prev, a]))
  }

  const save = async () => {
    setSaving(true)
    try {
      await onSave(day, selected, notes)
      setSavedFlash(true)
      setTimeout(() => setSavedFlash(false), 1500)
    } catch (err) {
      onError(friendlyError(err, 'Could not save the day.'))
    } finally {
      setSaving(false)
    }
  }

  const cleanDay = selected.length === 1

  return (
    <div className="bg-white rounded-lg shadow p-4" data-day={day}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="font-medium text-gray-900">{dayLabel(day)}</span>
          {cleanDay && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-green-100 text-green-800">
              clean day → {APPLIANCE_LABELS[selected[0]] || selected[0]}
            </span>
          )}
          {selected.length === 0 && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-600">nothing ran</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {savedFlash && <span className="text-xs text-green-600">saved</span>}
          <button
            onClick={save}
            disabled={saving}
            data-save
            className="px-3 py-1 rounded-md text-sm font-medium bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        {APPLIANCES.map((a) => {
          const on = selected.includes(a)
          return (
            <button
              key={a}
              type="button"
              onClick={() => toggle(a)}
              data-appliance={a}
              aria-pressed={on}
              className={`px-2.5 py-1 rounded-md text-xs font-medium border ${
                on ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-100'
              }`}
            >
              {APPLIANCE_LABELS[a] || a}
            </button>
          )
        })}
      </div>
      <input
        type="text"
        placeholder="Notes (optional)"
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        className="mt-2 w-full px-2 py-1.5 border border-gray-300 rounded-md text-sm"
      />
    </div>
  )
}

function LogTab({ log, setLog, logSubmitting, logMessage, submitLog }) {
  const field = (k) => (v) => setLog((prev) => ({ ...prev, [k]: v }))
  return (
    <div className="bg-white rounded-lg shadow p-6 max-w-xl">
      <h3 className="text-lg font-semibold text-gray-900 mb-4">Log an event</h3>
      <p className="text-sm text-gray-500 mb-4">
        Record something that just happened, or plan ahead (&ldquo;Cosy tonight at 3am&rdquo;). For a
        deliberate isolation test, set cleanliness to <em>clean isolated</em>.
      </p>
      <div className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Appliance</label>
          <select
            value={log.appliance}
            onChange={(e) => field('appliance')(e.target.value)}
            className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
          >
            {APPLIANCES.map((a) => (
              <option key={a} value={a}>{APPLIANCE_LABELS[a] || a}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Start (local time)</label>
          <input
            type="datetime-local"
            value={log.startLocal}
            onChange={(e) => field('startLocal')(e.target.value)}
            className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
          />
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Duration (min, optional)</label>
            <input
              type="number"
              min="0"
              placeholder="e.g. 35"
              value={log.durationMin}
              onChange={(e) => field('durationMin')(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Status</label>
            <select
              value={log.status}
              onChange={(e) => field('status')(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
            >
              <option value="confirmed">Happened</option>
              <option value="planned">Planned</option>
            </select>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Energy (kWh, optional)</label>
            <input
              type="number"
              step="0.01"
              min="0"
              placeholder="e.g. 1.2"
              value={log.energyKwh}
              onChange={(e) => field('energyKwh')(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
            />
          </div>
          {log.appliance === 'cosy' && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Target temp</label>
              <select
                value={log.targetTemp}
                onChange={(e) => field('targetTemp')(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
              >
                <option value="">—</option>
                <option value="50">50°C</option>
                <option value="60">60°C</option>
              </select>
            </div>
          )}
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Was anything else running?</label>
          <CleanlinessControl value={log.cleanliness} onChange={field('cleanliness')} />
        </div>
        <button
          onClick={submitLog}
          disabled={logSubmitting}
          className="bg-blue-600 text-white py-2 px-5 rounded-md font-medium hover:bg-blue-700 disabled:opacity-50"
        >
          {logSubmitting ? 'Logging…' : 'Log event'}
        </button>
        {logMessage && (
          <p className={`text-sm ${logMessage.ok ? 'text-green-600' : 'text-red-600'}`}>{logMessage.text}</p>
        )}
      </div>
    </div>
  )
}
