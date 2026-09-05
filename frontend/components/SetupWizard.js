import { useState, useEffect } from 'react'
import { supabase } from '@/lib/supabaseClient'

const STEPS = ['Site', 'Battery', 'Tariff', 'Credentials']

export default function SetupWizard({ apiUrl, onComplete }) {
  const [step, setStep] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [siteId, setSiteId] = useState(null)
  const [session, setSession] = useState(null)

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      setSession(data?.session)
    })
  }, [])

  const [siteData, setSiteData] = useState({ name: 'Home', timezone: 'Europe/London' })
  const [batteryData, setBatteryData] = useState({
    capacity_kwh: 5.0,
    max_charge_kw: 3.0,
    max_discharge_kw: 3.0,
    min_soc_pct: 20.0,
    max_soc_pct: 100.0,
    provider_type: 'foxess',
  })
  const [tariffData, setTariffData] = useState({
    import_type: 'agile',
    export_type: 'agile',
    region_code: 'E',
  })
  const [credData, setCredData] = useState({
    solcast_api_key: '',
    solcast_system_id: '',
    foxess_api_key: '',
  })

  const getHeaders = () => ({
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${session?.access_token}`,
  })

  const handleCreateSite = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${apiUrl}/sites`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify(siteData),
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'Failed to create site')
      }
      const data = await res.json()
      setSiteId(data.site.id)
      setStep(1)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const handleCreateBattery = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${apiUrl}/batteries`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({
          site_id: siteId,
          ...batteryData,
          provider_config: {
            solcast_api_key: credData.solcast_api_key,
            solcast_system_id: credData.solcast_system_id,
            foxess_api_key: credData.foxess_api_key,
          },
        }),
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'Failed to save battery config')
      }
      setStep(2)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const handleCreateTariff = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${apiUrl}/tariffs`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({
          site_id: siteId,
          import_type: tariffData.import_type,
          export_type: tariffData.export_type,
          config_json: { region_code: tariffData.region_code },
        }),
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'Failed to save tariff')
      }
      setStep(3)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const handleFinish = () => {
    onComplete(siteId)
  }

  if (!session) {
    return (
      <div className="bg-white rounded-lg shadow p-6 max-w-md mx-auto">
        <p className="text-gray-500">Loading...</p>
      </div>
    )
  }

  const inputClass = "w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-blue-500 focus:border-blue-500"
  const labelClass = "block text-sm font-medium text-gray-700 mb-1"

  return (
    <div className="bg-white rounded-lg shadow p-6 max-w-md mx-auto">
      <h2 className="text-xl font-bold text-gray-900 mb-2">Set Up Your Energy Optimiser</h2>
      <p className="text-sm text-gray-500 mb-6">Step {step + 1} of {STEPS.length}: {STEPS[step]}</p>

      {/* Progress bar */}
      <div className="flex gap-2 mb-6">
        {STEPS.map((s, i) => (
          <div key={s} className={`h-1 flex-1 rounded ${i <= step ? 'bg-blue-600' : 'bg-gray-200'}`} />
        ))}
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded p-3 mb-4">
          <p className="text-red-700 text-sm">{error}</p>
        </div>
      )}

      {/* Step 0: Site */}
      {step === 0 && (
        <div className="space-y-4">
          <div>
            <label className={labelClass}>Site Name</label>
            <input
              type="text"
              value={siteData.name}
              onChange={(e) => setSiteData({ ...siteData, name: e.target.value })}
              className={inputClass}
              placeholder="e.g. Home - Stroud"
            />
          </div>
          <div>
            <label className={labelClass}>Timezone</label>
            <select
              value={siteData.timezone}
              onChange={(e) => setSiteData({ ...siteData, timezone: e.target.value })}
              className={inputClass}
            >
              <option value="Europe/London">Europe/London</option>
              <option value="Europe/Madrid">Europe/Madrid</option>
              <option value="Asia/Bangkok">Asia/Bangkok</option>
            </select>
          </div>
          <button onClick={handleCreateSite} disabled={loading}
            className="w-full bg-blue-600 text-white py-2 px-4 rounded-md font-medium hover:bg-blue-700 disabled:opacity-50">
            {loading ? 'Creating...' : 'Next'}
          </button>
        </div>
      )}

      {/* Step 1: Battery */}
      {step === 1 && (
        <div className="space-y-4">
          <div>
            <label className={labelClass}>Battery Capacity (kWh)</label>
            <input type="number" value={batteryData.capacity_kwh}
              onChange={(e) => setBatteryData({ ...batteryData, capacity_kwh: Number(e.target.value) })}
              className={inputClass} step={0.5} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={labelClass}>Max Charge (kW)</label>
              <input type="number" value={batteryData.max_charge_kw}
                onChange={(e) => setBatteryData({ ...batteryData, max_charge_kw: Number(e.target.value) })}
                className={inputClass} step={0.5} />
            </div>
            <div>
              <label className={labelClass}>Max Discharge (kW)</label>
              <input type="number" value={batteryData.max_discharge_kw}
                onChange={(e) => setBatteryData({ ...batteryData, max_discharge_kw: Number(e.target.value) })}
                className={inputClass} step={0.5} />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={labelClass}>Min SOC (%)</label>
              <input type="number" value={batteryData.min_soc_pct}
                onChange={(e) => setBatteryData({ ...batteryData, min_soc_pct: Number(e.target.value) })}
                className={inputClass} min={0} max={100} />
            </div>
            <div>
              <label className={labelClass}>Max SOC (%)</label>
              <input type="number" value={batteryData.max_soc_pct}
                onChange={(e) => setBatteryData({ ...batteryData, max_soc_pct: Number(e.target.value) })}
                className={inputClass} min={0} max={100} />
            </div>
          </div>
          <button onClick={handleCreateBattery} disabled={loading}
            className="w-full bg-blue-600 text-white py-2 px-4 rounded-md font-medium hover:bg-blue-700 disabled:opacity-50">
            {loading ? 'Saving...' : 'Next'}
          </button>
        </div>
      )}

      {/* Step 2: Tariff */}
      {step === 2 && (
        <div className="space-y-4">
          <div>
            <label className={labelClass}>Import Tariff Type</label>
            <select value={tariffData.import_type}
              onChange={(e) => setTariffData({ ...tariffData, import_type: e.target.value })}
              className={inputClass}>
              <option value="agile">Octopus Agile</option>
              <option value="fixed">Fixed Rate</option>
              <option value="time_of_use">Time of Use</option>
            </select>
          </div>
          <div>
            <label className={labelClass}>Export Tariff Type</label>
            <select value={tariffData.export_type}
              onChange={(e) => setTariffData({ ...tariffData, export_type: e.target.value })}
              className={inputClass}>
              <option value="agile">Octopus Agile Outgoing</option>
              <option value="fixed">Fixed Export</option>
              <option value="none">No Export</option>
            </select>
          </div>
          <div>
            <label className={labelClass}>Region Code</label>
            <select value={tariffData.region_code}
              onChange={(e) => setTariffData({ ...tariffData, region_code: e.target.value })}
              className={inputClass}>
              <option value="A">A - Scotland</option>
              <option value="B">B - Southern Scotland</option>
              <option value="C">C - North England</option>
              <option value="D">D - South Wales</option>
              <option value="E">E - Midlands</option>
              <option value="F">F - South England</option>
              <option value="G">G - London</option>
              <option value="H">H - Southern England</option>
              <option value="J">J - North Scotland</option>
              <option value="K">K - Central Scotland</option>
            </select>
          </div>
          <button onClick={handleCreateTariff} disabled={loading}
            className="w-full bg-blue-600 text-white py-2 px-4 rounded-md font-medium hover:bg-blue-700 disabled:opacity-50">
            {loading ? 'Saving...' : 'Next'}
          </button>
        </div>
      )}

      {/* Step 3: Credentials */}
      {step === 3 && (
        <div className="space-y-4">
          <p className="text-sm text-gray-600">
            Enter your API keys to enable data fetching. These are stored securely in your account only.
          </p>
          <div>
            <label className={labelClass}>Solcast API Key</label>
            <input type="password" value={credData.solcast_api_key}
              onChange={(e) => setCredData({ ...credData, solcast_api_key: e.target.value })}
              className={inputClass} placeholder="Your Solcast API key" />
          </div>
          <div>
            <label className={labelClass}>Solcast PV System ID</label>
            <input type="text" value={credData.solcast_system_id}
              onChange={(e) => setCredData({ ...credData, solcast_system_id: e.target.value })}
              className={inputClass} placeholder="e.g. feae-7d5c-b618-0bfa" />
          </div>
          <div>
            <label className={labelClass}>FoxESS API Key</label>
            <input type="password" value={credData.foxess_api_key}
              onChange={(e) => setCredData({ ...credData, foxess_api_key: e.target.value })}
              className={inputClass} placeholder="Your FoxESS API key" />
          </div>
          <button onClick={handleFinish}
            className="w-full bg-green-600 text-white py-2 px-4 rounded-md font-medium hover:bg-green-700">
            Complete Setup
          </button>
        </div>
      )}
    </div>
  )
}
