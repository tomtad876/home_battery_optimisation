import {
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'

export default function ScheduleCharts({ schedule }) {
  if (!schedule || schedule.length === 0) return null

  // Prepare data for charts - use hourly aggregation for readability
  const hourlyData = []
  for (let i = 0; i < schedule.length; i += 2) {
    const period1 = schedule[i]
    const period2 = i + 1 < schedule.length ? schedule[i + 1] : period1

    const hour = new Date(period1.PeriodEnd).toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    })

    hourlyData.push({
      time: hour,
      solar: (period1.solar + (period2?.solar || 0)) / 2,
      demand: (period1.demand + (period2?.demand || 0)) / 2,
      price: (period1.price + (period2?.price || 0)) / 2,
      soc_pct: period2?.soc_pct || period1.soc_pct,
      batt_charge: (period1.batt_charge_kwh + (period2?.batt_charge_kwh || 0)) / 2,
      batt_discharge: (period1.batt_discharge_kwh + (period2?.batt_discharge_kwh || 0)) / 2,
      grid_import: (period1.grid_import_kwh + (period2?.grid_import_kwh || 0)) / 2,
      grid_export: (period1.grid_export_kwh + (period2?.grid_export_kwh || 0)) / 2,
    })
  }

  return (
    <div className="space-y-8">
      {/* Solar, Demand, Price Chart */}
      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Solar, Demand & Price</h3>
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={hourlyData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="time" angle={-45} textAnchor="end" height={80} />
            <YAxis yAxisId="left" label={{ value: 'kWh', angle: -90, position: 'insideLeft' }} />
            <YAxis yAxisId="right" orientation="right" label={{ value: 'pence/kWh', angle: 90, position: 'insideRight' }} />
            <Tooltip />
            <Legend />
            <Line yAxisId="left" type="monotone" dataKey="solar" stroke="#FBBF24" name="Solar (kWh)" strokeWidth={2} dot={false} />
            <Line yAxisId="left" type="monotone" dataKey="demand" stroke="#A78BFA" name="Demand (kWh)" strokeWidth={2} dot={false} />
            <Line yAxisId="right" type="monotone" dataKey="price" stroke="#EF4444" name="Price (p/kWh)" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Battery State of Charge */}
      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Battery State of Charge</h3>
        <ResponsiveContainer width="100%" height={250}>
          <LineChart data={hourlyData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="time" angle={-45} textAnchor="end" height={80} />
            <YAxis label={{ value: 'SOC (%)', angle: -90, position: 'insideLeft' }} domain={[0, 100]} />
            <Tooltip />
            <Legend />
            <Line type="monotone" dataKey="soc_pct" stroke="#3B82F6" name="SOC (%)" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Battery Charge/Discharge */}
      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Battery Actions</h3>
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={hourlyData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="time" angle={-45} textAnchor="end" height={80} />
            <YAxis label={{ value: 'Energy (kWh)', angle: -90, position: 'insideLeft' }} />
            <Tooltip />
            <Legend />
            <Bar dataKey="batt_charge" fill="#10B981" name="Charge (kWh)" />
            <Bar dataKey="batt_discharge" fill="#F59E0B" name="Discharge (kWh)" />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Grid Import/Export */}
      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Grid Energy</h3>
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={hourlyData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="time" angle={-45} textAnchor="end" height={80} />
            <YAxis label={{ value: 'Energy (kWh)', angle: -90, position: 'insideLeft' }} />
            <Tooltip />
            <Legend />
            <Bar dataKey="grid_import" fill="#EF4444" name="Import (kWh)" />
            <Bar dataKey="grid_export" fill="#22C55E" name="Export (kWh)" />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Energy Balance Sankey-like view using stacked data */}
      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Cumulative Cost</h3>
        <ResponsiveContainer width="100%" height={250}>
          <LineChart data={hourlyData.map((d, i) => ({
            ...d,
            cumulative_cost: hourlyData.slice(0, i + 1).reduce((sum, x) => sum + (x.grid_import * x.price / 100 - x.grid_export * 15 / 100), 0)
          }))}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="time" angle={-45} textAnchor="end" height={80} />
            <YAxis label={{ value: 'Cost (£)', angle: -90, position: 'insideLeft' }} />
            <Tooltip formatter={(value) => value.toFixed(2)} />
            <Legend />
            <Line type="monotone" dataKey="cumulative_cost" stroke="#8B5CF6" name="Cumulative Cost (£)" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
