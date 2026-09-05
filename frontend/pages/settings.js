import { useState, useEffect } from 'react';
import { createClient } from '@supabase/supabase-js';

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY
);

export default function CredentialsSettings() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState(null);
  const [batteryId, setBatteryId] = useState(null);

  const [solcastApiKey, setSolcastApiKey] = useState('');
  const [solcastSystemId, setSolcastSystemId] = useState('');
  const [foxessApiKey, setFoxessApiKey] = useState('');
  const [foxessDeviceSn, setFoxessDeviceSn] = useState('');

  const [capacityKwh, setCapacityKwh] = useState('13.5');
  const [maxChargeKw, setMaxChargeKw] = useState('5.0');
  const [maxDischargeKw, setMaxDischargeKw] = useState('5.0');
  const [minSocPct, setMinSocPct] = useState('20');
  const [maxSocPct, setMaxSocPct] = useState('100');

  useEffect(() => {
    loadCredentials();
  }, []);

  async function loadCredentials() {
    setLoading(true);
    setMessage(null);
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return;

      let resp = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/batteries/me`, {
        headers: { Authorization: `Bearer ${session.access_token}` },
      });

      // If no battery exists, create a default one
      if (resp.status === 404) {
        const siteResp = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/sites/me`, {
          headers: { Authorization: `Bearer ${session.access_token}` },
        });
        if (!siteResp.ok) {
          setMessage({ type: 'error', text: 'No site found. Please complete the setup wizard first.' });
          return;
        }
        const siteData = await siteResp.json();
        const createResp = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/batteries`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${session.access_token}`,
          },
          body: JSON.stringify({
            site_id: siteData.site.id,
            capacity_kwh: 13.5,
            max_charge_kw: 5.0,
            max_discharge_kw: 5.0,
            min_soc_pct: 20.0,
            max_soc_pct: 100.0,
            provider_type: 'foxess',
            provider_config: {},
          }),
        });
        if (createResp.ok) {
          resp = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/batteries/me`, {
            headers: { Authorization: `Bearer ${session.access_token}` },
          });
        }
      }

      if (resp.ok) {
        const data = await resp.json();
        const config = data.battery?.provider_config || {};
        setBatteryId(data.battery?.id);
        setSolcastApiKey(config.solcast_api_key || '');
        setSolcastSystemId(config.solcast_system_id || '');
        setFoxessApiKey(config.foxess_api_key || '');
        setFoxessDeviceSn(config.foxess_device_sn || '');
        setCapacityKwh(String(data.battery?.capacity_kwh ?? '13.5'));
        setMaxChargeKw(String(data.battery?.max_charge_kw ?? '5.0'));
        setMaxDischargeKw(String(data.battery?.max_discharge_kw ?? '5.0'));
        setMinSocPct(String(data.battery?.min_soc_pct ?? '20'));
        setMaxSocPct(String(data.battery?.max_soc_pct ?? '100'));
      }
    } catch (e) {
      console.error('Failed to load credentials:', e);
    } finally {
      setLoading(false);
    }
  }

  async function handleSave(e) {
    e.preventDefault();
    setSaving(true);
    setMessage(null);

    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return;

      const headers = {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${session.access_token}`,
      };

      // Save battery config
      const battResp = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/batteries/me`, {
        method: 'PUT',
        headers,
        body: JSON.stringify({
          capacity_kwh: parseFloat(capacityKwh) || 13.5,
          max_charge_kw: parseFloat(maxChargeKw) || 5.0,
          max_discharge_kw: parseFloat(maxDischargeKw) || 5.0,
          min_soc_pct: parseFloat(minSocPct) || 20,
          max_soc_pct: parseFloat(maxSocPct) || 100,
        }),
      });

      // Save API credentials
      const credBody = {};
      if (solcastApiKey) credBody.solcast_api_key = solcastApiKey;
      if (solcastSystemId) credBody.solcast_system_id = solcastSystemId;
      if (foxessApiKey) credBody.foxess_api_key = foxessApiKey;
      if (foxessDeviceSn) credBody.foxess_device_sn = foxessDeviceSn;

      const credResp = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/batteries/me/provider_config`, {
        method: 'PUT',
        headers,
        body: JSON.stringify(credBody),
      });

      if (battResp.ok && credResp.ok) {
        setMessage({ type: 'success', text: 'Settings saved successfully.' });
      } else {
        const err = await (battResp.ok ? credResp : battResp).json();
        setMessage({ type: 'error', text: err.detail || 'Failed to save.' });
      }
    } catch (e) {
      setMessage({ type: 'error', text: 'Network error.' });
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div style={styles.container}>
        <div style={styles.card}>
          <p style={styles.loading}>Loading...</p>
        </div>
      </div>
    );
  }

  return (
    <div style={styles.container}>
      <div style={styles.card}>
        <h1 style={styles.title}>API Credentials</h1>
        <p style={styles.subtitle}>
          Configure your Solcast and FoxESS API keys. These are used to fetch solar forecasts and energy usage data for optimisation.
        </p>

        {message && (
          <div style={{
            ...styles.message,
            backgroundColor: message.type === 'success' ? '#d4edda' : '#f8d7da',
            color: message.type === 'success' ? '#155724' : '#721c24',
            borderColor: message.type === 'success' ? '#c3e6cb' : '#f5c6cb',
          }}>
            {message.text}
          </div>
        )}

        <form onSubmit={handleSave}>
          <h2 style={styles.sectionTitle}>Battery Configuration</h2>

          <div style={styles.row}>
            <div style={styles.halfField}>
              <label style={styles.label}>Capacity (kWh)</label>
              <input
                type="number"
                step="0.1"
                value={capacityKwh}
                onChange={(e) => setCapacityKwh(e.target.value)}
                style={styles.input}
              />
            </div>
            <div style={styles.halfField}>
              <label style={styles.label}>Max Charge (kW)</label>
              <input
                type="number"
                step="0.1"
                value={maxChargeKw}
                onChange={(e) => setMaxChargeKw(e.target.value)}
                style={styles.input}
              />
            </div>
          </div>

          <div style={styles.row}>
            <div style={styles.halfField}>
              <label style={styles.label}>Max Discharge (kW)</label>
              <input
                type="number"
                step="0.1"
                value={maxDischargeKw}
                onChange={(e) => setMaxDischargeKw(e.target.value)}
                style={styles.input}
              />
            </div>
            <div style={styles.halfField}>
              <label style={styles.label}>Min SOC (%)</label>
              <input
                type="number"
                step="1"
                value={minSocPct}
                onChange={(e) => setMinSocPct(e.target.value)}
                style={styles.input}
              />
            </div>
          </div>

          <div style={styles.row}>
            <div style={styles.halfField}>
              <label style={styles.label}>Max SOC (%)</label>
              <input
                type="number"
                step="1"
                value={maxSocPct}
                onChange={(e) => setMaxSocPct(e.target.value)}
                style={styles.input}
              />
            </div>
            <div style={styles.halfField} />
          </div>

          <h2 style={styles.sectionTitle}>API Credentials</h2>

          <label style={styles.label}>API Key</label>
          <input
            type="password"
            value={solcastApiKey}
            onChange={(e) => setSolcastApiKey(e.target.value)}
            placeholder="Your Solcast API key"
            style={styles.input}
          />

          <label style={styles.label}>PV System ID</label>
          <input
            type="text"
            value={solcastSystemId}
            onChange={(e) => setSolcastSystemId(e.target.value)}
            placeholder="e.g. 7a6e5f2e-..."
            style={styles.input}
          />

          <h2 style={styles.sectionTitle}>FoxESS (Energy Usage)</h2>

          <label style={styles.label}>API Key (Token)</label>
          <input
            type="password"
            value={foxessApiKey}
            onChange={(e) => setFoxessApiKey(e.target.value)}
            placeholder="Your FoxESS API token"
            style={styles.input}
          />

          <label style={styles.label}>Device Serial Number</label>
          <input
            type="text"
            value={foxessDeviceSn}
            onChange={(e) => setFoxessDeviceSn(e.target.value)}
            placeholder="Your FoxESS device SN"
            style={styles.input}
          />

          <button
            type="submit"
            disabled={saving}
            style={{
              ...styles.button,
              opacity: saving ? 0.6 : 1,
            }}
          >
            {saving ? 'Saving...' : 'Save Credentials'}
          </button>
        </form>

        <p style={styles.hint}>
          Keys are stored encrypted in your account. They are only used by the background data fetcher to pull your solar forecast and usage history.
        </p>
      </div>
    </div>
  );
}

const styles = {
  container: {
    minHeight: '100vh',
    background: 'linear-gradient(135deg, #0f172a 0%, #1e293b 100%)',
    display: 'flex',
    justifyContent: 'center',
    alignItems: 'flex-start',
    padding: '40px 20px',
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
  },
  card: {
    background: '#fff',
    borderRadius: '12px',
    padding: '40px',
    maxWidth: '520px',
    width: '100%',
    boxShadow: '0 4px 24px rgba(0,0,0,0.15)',
  },
  title: {
    fontSize: '24px',
    fontWeight: '700',
    color: '#1e293b',
    margin: '0 0 8px 0',
  },
  subtitle: {
    fontSize: '14px',
    color: '#64748b',
    margin: '0 0 24px 0',
    lineHeight: '1.5',
  },
  sectionTitle: {
    fontSize: '16px',
    fontWeight: '600',
    color: '#334155',
    margin: '24px 0 12px 0',
    paddingBottom: '6px',
    borderBottom: '1px solid #e2e8f0',
  },
  label: {
    display: 'block',
    fontSize: '13px',
    fontWeight: '500',
    color: '#475569',
    marginBottom: '4px',
    marginTop: '12px',
  },
  input: {
    width: '100%',
    padding: '10px 12px',
    border: '1px solid #cbd5e1',
    borderRadius: '6px',
    fontSize: '14px',
    fontFamily: 'monospace',
    boxSizing: 'border-box',
    outline: 'none',
  },
  button: {
    marginTop: '24px',
    width: '100%',
    padding: '12px',
    background: '#2563eb',
    color: '#fff',
    border: 'none',
    borderRadius: '8px',
    fontSize: '16px',
    fontWeight: '600',
    cursor: 'pointer',
  },
  message: {
    padding: '12px 16px',
    borderRadius: '8px',
    border: '1px solid',
    marginBottom: '16px',
    fontSize: '14px',
  },
  hint: {
    marginTop: '20px',
    fontSize: '12px',
    color: '#94a3b8',
    lineHeight: '1.5',
  },
  loading: {
    textAlign: 'center',
    color: '#64748b',
  },
  row: {
    display: 'flex',
    gap: '12px',
  },
  halfField: {
    flex: 1,
  },
};
