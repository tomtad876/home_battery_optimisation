import { useState } from 'react'

export default function OptimiserForm({ onSubmit, loading }) {
  const [formData, setFormData] = useState({
    battery_capacity_kwh: 5.0,
    initial_soc_pct: 50.0,
    min_soc_pct: 20.0,
    max_soc_pct: 100.0,
    charge_power_kw: 3.0,
    discharge_power_kw: 3.0,
    export_price_pence: 15.0,
  })

  const handleChange = (e) => {
    const { name, value } = e.target
    setFormData((prev) => ({
      ...prev,
      [name]: isNaN(value) ? value : Number(value),
    }))
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    onSubmit(formData)
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <h2 className="text-lg font-semibold text-gray-900 mb-4">Battery Config</h2>



      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Battery Capacity (kWh)
        </label>
        <input
          type="number"
          name="battery_capacity_kwh"
          value={formData.battery_capacity_kwh}
          onChange={handleChange}
          step={1}
          className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-blue-500 focus:border-blue-500"
        />
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Initial SOC (%)
        </label>
        <input
          type="number"
          name="initial_soc_pct"
          value={formData.initial_soc_pct}
          onChange={handleChange}
          min={0}
          max={100}
          className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-blue-500 focus:border-blue-500"
        />
      </div>

      <div className="border-t pt-4">
        <h3 className="text-sm font-medium text-gray-700 mb-3">SOC Bounds</h3>
        <div className="space-y-3">
          <div>
            <label className="text-xs text-gray-600">Min (%)</label>
            <input
              type="number"
              name="min_soc_pct"
              value={formData.min_soc_pct}
              onChange={handleChange}
              min={0}
              max={100}
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-blue-500 focus:border-blue-500"
            />
          </div>
          <div>
            <label className="text-xs text-gray-600">Max (%)</label>
            <input
              type="number"
              name="max_soc_pct"
              value={formData.max_soc_pct}
              onChange={handleChange}
              min={0}
              max={100}
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-blue-500 focus:border-blue-500"
            />
          </div>
        </div>
      </div>

      <div className="border-t pt-4">
        <h3 className="text-sm font-medium text-gray-700 mb-3">Power Limits (kW)</h3>
        <div className="space-y-3">
          <div>
            <label className="text-xs text-gray-600">Charge (kW)</label>
            <input
              type="number"
              name="charge_power_kw"
              value={formData.charge_power_kw}
              onChange={handleChange}
              step={0.5}
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-blue-500 focus:border-blue-500"
            />
          </div>
          <div>
            <label className="text-xs text-gray-600">Discharge (kW)</label>
            <input
              type="number"
              name="discharge_power_kw"
              value={formData.discharge_power_kw}
              onChange={handleChange}
              step={0.5}
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-blue-500 focus:border-blue-500"
            />
          </div>
        </div>
      </div>

      <div className="border-t pt-4">
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Export Price (p/kWh)
        </label>
        <input
          type="number"
          name="export_price_pence"
          value={formData.export_price_pence}
          onChange={handleChange}
          step={0.5}
          className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-blue-500 focus:border-blue-500"
        />
      </div>

      <button
        type="submit"
        disabled={loading}
        className="w-full bg-blue-600 text-white py-2 px-4 rounded-md font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed mt-6"
      >
        {loading ? 'Optimising...' : 'Optimise'}
      </button>
    </form>
  )
}
