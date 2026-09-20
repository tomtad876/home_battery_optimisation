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

const APPLIANCES = [
  'cosy', 'washing_machine', 'tumble_dryer', 'dishwasher', 'oven', 'heating', 'gaming', 'other',
]

const APPLIANCE_LABELS = {
  cosy: 'Cosy (water tank)',
  washing_machine: 'Washing machine',
  tumble_dryer: 'Tumble dryer',
  dishwasher: 'Dishwasher',
  oven: 'Oven / cooker',
  heating: 'Heating',
  gaming: 'Gaming / PC',
  other: 'Other',
  not_appliance: 'Not an appliance',
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

export default function Events() {
  const [user, setUser] = useState(null)
  const [site, setSite] = useState(null)
  const [siteLoading, setSiteLoading] = useState(true)
  const [siteError, setSiteError] = useState(null)
  const [tab, setTab] = useState('review')
  const [candidates, setCandidates] = useState([])
  const [labelled, setLabelled] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [busyKey, setBusyKey] = useState(null)
  const [editingKey, setEditingKey] = useState(null)

  // Log form state
  const [log, setLog] = useState({
    appliance: 'cosy', startLocal: '', durationMin: '', status: 'confirmed', energyKwh: '',
  })
  const [logSubmitting, setLogSubmitting] = useState(false)
  const [logMessage, setLogMessage] = useState(null)

  const loadData = useCallback(async (accessToken) => {
    setLoading(true)
    setError(null)
    try {
      const [detected, existing] = await Promise.all([
        apiFetch('/events/detect?days=7', { accessToken }),
        apiFetch('/events', { accessToken }),
      ])
      setCandidates(detected?.events || [])
      setLabelled(existing?.events || [])
    } catch (err) {
      setError(friendlyError(err, 'Could not load events.'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    let mounted = true
    supabase.auth.getSession().then(({ data }) => {
      if (!mounted) return
      const u = data?.session?.user ?? null
      setUser(u)
      if (u && data?.session?.access_token) {
        apiFetch('/sites/me', { accessToken: data.session.access_token })
          .then((res) => {
            if (!mounted) return
            setSite(res?.site ?? null)
            loadData(data.session.access_token)
          })
          .catch((err) => {
            if (!mounted) return
            if (err?.status !== 404) setSiteError(friendlyError(err, 'Could not load your site.'))
            setSite(null)
          })
          .finally(() => mounted && setSiteLoading(false))
      } else {
        setSiteLoading(false)
      }
    })

    const { data: listener } = supabase.auth.onAuthStateChange((event, session) => {
      if (!mounted) return
      if (event === 'SIGNED_IN') {
        setUser(session?.user ?? null)
        setSiteLoading(true)
        if (session?.access_token) loadData(session.access_token)
      } else if (event === 'SIGNED_OUT') {
        setUser(null)
        setSite(null)
        setCandidates([])
        setLabelled([])
        setSiteLoading(false)
      }
    })

    return () => {
      mounted = false
      listener?.subscription?.unsubscribe?.()
    }
  }, [loadData])

  const getToken = async () => (await supabase.auth.getSession()).data?.session?.access_token

  const confirmCandidate = async (candidate, appliance) => {
    setBusyKey(candidate.start_time)
    try {
      const accessToken = await getToken()
      await apiFetch('/events', {
        method: 'POST',
        accessToken,
        body: {
          appliance,
          start_time: candidate.start_time,
          end_time: candidate.end_time,
          status: 'confirmed',
          energy_kwh: candidate.energy_kwh,
          source: 'review',
        },
      })
      setCandidates((prev) => prev.filter((c) => c.start_time !== candidate.start_time))
      const existing = await apiFetch('/events', { accessToken })
      setLabelled(existing?.events || [])
      setEditingKey(null)
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
      await apiFetch('/events', {
        method: 'POST',
        accessToken,
        body: {
          appliance: log.appliance,
          start_time: start,
          end_time: end,
          status: log.status,
          energy_kwh: log.energyKwh === '' ? null : Number(log.energyKwh),
          source: 'manual',
        },
      })
      setLog({ appliance: 'cosy', startLocal: '', durationMin: '', status: 'confirmed', energyKwh: '' })
      setLogMessage({ ok: true, text: 'Logged.' })
      const existing = await apiFetch('/events', { accessToken })
      setLabelled(existing?.events || [])
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
                <button
                  onClick={() => setTab('review')}
                  className={`px-4 py-2 rounded-md font-medium text-sm ${
                    tab === 'review' ? 'bg-blue-600 text-white' : 'bg-white text-gray-700 hover:bg-gray-100 border border-gray-300'
                  }`}
                >
                  Review {candidates.length > 0 && <span className="ml-1 bg-white/20 rounded-full px-2 py-0.5 text-xs">{candidates.length}</span>}
                </button>
                <button
                  onClick={() => setTab('log')}
                  className={`px-4 py-2 rounded-md font-medium text-sm ${
                    tab === 'log' ? 'bg-blue-600 text-white' : 'bg-white text-gray-700 hover:bg-gray-100 border border-gray-300'
                  }`}
                >
                  Log event
                </button>
              </div>

              {error && (
                <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-6">
                  <p className="text-red-800 text-sm">{error}</p>
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
                  editingKey={editingKey}
                  setEditingKey={setEditingKey}
                  confirmCandidate={confirmCandidate}
                  deleteEvent={deleteEvent}
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

function ReviewTab({ days, grouped, loading, candidates, labelled, busyKey, editingKey, setEditingKey, confirmCandidate, deleteEvent }) {
  return (
    <div className="space-y-8">
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
              const editing = editingKey === c.start_time
              return (
                <div key={c.start_time} className="bg-white rounded-lg shadow p-4">
                  <div className="flex items-start gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-sm font-medium text-gray-900">
                          {c.start_local.slice(11)}–{c.end_local}
                        </span>
                        <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${
                          c.confidence >= 0.7 ? 'bg-green-100 text-green-800' : 'bg-yellow-100 text-yellow-800'
                        }`}>
                          {c.suggested_appliance === 'not_appliance' ? '—' : APPLIANCE_LABELS[c.suggested_appliance] || c.suggested_appliance}
                        </span>
                        <span className="text-xs text-gray-400">
                          {c.dur_min} min · {c.peak_kw} kW peak · {c.energy_kwh} kWh
                        </span>
                      </div>
                      <div className="mt-2 text-xs text-gray-400">
                        {c.confidence >= 0.7 ? 'confident' : 'guess'} (flatness {c.flatness})
                      </div>
                    </div>
                    <div className="w-40 shrink-0">
                      <Sparkline trace={c.trace} />
                    </div>
                  </div>

                  <div className="mt-3 flex items-center gap-2">
                    <button
                      onClick={() => confirmCandidate(c, c.suggested_appliance)}
                      disabled={busy}
                      className="px-3 py-1.5 rounded-md text-sm font-medium bg-green-600 text-white hover:bg-green-700 disabled:opacity-50"
                    >
                      ✓ Confirm
                    </button>
                    {editing ? (
                      <>
                        <select
                          autoFocus
                          value={c.suggested_appliance}
                          onChange={(e) => confirmCandidate(c, e.target.value)}
                          onBlur={() => setEditingKey(null)}
                          className="px-2 py-1.5 border border-gray-300 rounded-md text-sm"
                        >
                          {APPLIANCES.map((a) => (
                            <option key={a} value={a}>{APPLIANCE_LABELS[a] || a}</option>
                          ))}
                        </select>
                        <button onClick={() => setEditingKey(null)} className="text-sm text-gray-500">cancel</button>
                      </>
                    ) : (
                      <button
                        onClick={() => setEditingKey(c.start_time)}
                        disabled={busy}
                        className="px-3 py-1.5 rounded-md text-sm font-medium bg-blue-100 text-blue-700 hover:bg-blue-200 disabled:opacity-50"
                      >
                        ✎ Relabel
                      </button>
                    )}
                    <button
                      onClick={() => confirmCandidate(c, 'not_appliance')}
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

      {/* Already-labelled events */}
      {labelled.length > 0 && (
        <div className="pt-4 border-t border-gray-200">
          <h3 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">Labelled events ({labelled.length})</h3>
          <div className="space-y-2">
            {labelled.slice(0, 50).map((e) => (
              <div key={e.id} className="flex items-center justify-between bg-white rounded-lg shadow px-4 py-2">
                <div className="flex items-center gap-3 text-sm">
                  <span className="font-medium text-gray-800">{APPLIANCE_LABELS[e.appliance] || e.appliance}</span>
                  <span className="text-gray-500">
                    {new Date(e.start_time).toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Europe/London' })}
                  </span>
                  <span className={`text-xs px-2 py-0.5 rounded-full ${
                    e.status === 'confirmed' ? 'bg-green-100 text-green-800'
                    : e.status === 'planned' ? 'bg-blue-100 text-blue-800'
                    : 'bg-gray-100 text-gray-600'
                  }`}>{e.status}</span>
                </div>
                <button onClick={() => deleteEvent(e.id)} className="text-sm text-red-500 hover:text-red-700">Delete</button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function LogTab({ log, setLog, logSubmitting, logMessage, submitLog }) {
  const field = (k) => (v) => setLog((prev) => ({ ...prev, [k]: v }))
  return (
    <div className="bg-white rounded-lg shadow p-6 max-w-xl">
      <h3 className="text-lg font-semibold text-gray-900 mb-4">Log an event</h3>
      <p className="text-sm text-gray-500 mb-4">
        Record something that just happened, or plan ahead (&ldquo;Cosy tonight at 3am&rdquo;).
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
