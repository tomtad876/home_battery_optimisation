import { useState, useEffect } from 'react';
import { supabase } from '@/lib/supabaseClient';
import { apiFetch, friendlyError } from '@/lib/api';

// Settings is split into three independent cards, each with its own save. The
// automatic-push and holiday toggles used to live inside the credentials form,
// so flipping a toggle looked like it did nothing until you clicked "Save
// Credentials" — and the toggle never reflected the saved value. Now household
// automation, battery config and API credentials are separate and save
// separately.
export default function SettingsPage() {
  const [loading, setLoading] = useState(true);
  const [savingSection, setSavingSection] = useState(null); // 'automation' | 'battery' | 'credentials'
  const [message, setMessage] = useState(null);
  const [batteryId, setBatteryId] = useState(null);

  const [solcastApiKey, setSolcastApiKey] = useState('');
  const [solcastSystemId, setSolcastSystemId] = useState('');
  const [foxessApiKey, setFoxessApiKey] = useState('');
  const [foxessDeviceSn, setFoxessDeviceSn] = useState('');
  const [octopusApiKey, setOctopusApiKey] = useState('');
  const [octopusAccountNumber, setOctopusAccountNumber] = useState('');

  const [capacityKwh, setCapacityKwh] = useState('5.0');
  const [maxChargeKw, setMaxChargeKw] = useState('3.0');
  const [maxDischargeKw, setMaxDischargeKw] = useState('3.0');
  const [minSocPct, setMinSocPct] = useState('20');
  const [maxSocPct, setMaxSocPct] = useState('100');

  const [autoPushEnabled, setAutoPushEnabled] = useState(false);
  const [holidayMode, setHolidayMode] = useState(false);
  const [holidayUntil, setHolidayUntil] = useState('');

  useEffect(() => {
    loadCredentials();
  }, []);

  async function loadCredentials() {
    setLoading(true);
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return;

      // Holiday settings live on the site, not the battery.
      let site = null;
      try {
        const siteData = await apiFetch('/sites/me', { accessToken: session.access_token });
        site = siteData?.site ?? null;
      } catch (err) {
        if (err?.status !== 404) throw err;
      }
      if (site) {
        setHolidayMode(site.holiday_mode ?? false);
        setHolidayUntil(site.holiday_until ? String(site.holiday_until).slice(0, 10) : '');
      }

      let battery = null;
      try {
        const data = await apiFetch('/batteries/me', { accessToken: session.access_token });
        battery = data?.battery ?? null;
      } catch (err) {
        // 404 = no battery yet; anything else is a real failure
        if (err?.status !== 404) throw err;
      }

      // If no battery exists, create a default one
      if (!battery) {
        if (!site) throw new Error('No site found. Complete setup first.');
        // Not safe to retry: a repeated create could add a second battery
        const created = await apiFetch('/batteries', {
          method: 'POST',
          accessToken: session.access_token,
          retryUnsafe: false,
          body: {
            site_id: site.id,
            capacity_kwh: 5.0,
            max_charge_kw: 3.0,
            max_discharge_kw: 3.0,
            min_soc_pct: 20.0,
            max_soc_pct: 100.0,
            provider_type: 'foxess',
            provider_config: {},
          },
        });
        battery = created?.battery ?? null;
      }

      if (battery) {
        const config = battery.provider_config || {};
        setBatteryId(battery.id);
        setSolcastApiKey(config.solcast_api_key || '');
        setSolcastSystemId(config.solcast_system_id || '');
        setFoxessApiKey(config.foxess_api_key || '');
        setFoxessDeviceSn(config.foxess_device_sn || '');
        setOctopusApiKey(config.octopus_api_key || '');
        setOctopusAccountNumber(config.octopus_account_number || '');
        setCapacityKwh(String(battery.capacity_kwh ?? '5.0'));
        setMaxChargeKw(String(battery.max_charge_kw ?? '3.0'));
        setMaxDischargeKw(String(battery.max_discharge_kw ?? '3.0'));
        setMinSocPct(String(battery.min_soc_pct ?? '20'));
        setMaxSocPct(String(battery.max_soc_pct ?? '100'));
        // This is why the toggle used to reset to off: the GET didn't return it.
        setAutoPushEnabled(battery.auto_push_enabled ?? false);
      } else {
        setMessage({ type: 'error', text: 'No battery found. Please complete the setup wizard first.' });
      }
    } catch (err) {
      setMessage({ type: 'error', text: friendlyError(err, 'Failed to load settings.') });
    } finally {
      setLoading(false);
    }
  }

  async function withSession(section, fn) {
    setSavingSection(section);
    setMessage(null);
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return;
      await fn(session.access_token);
    } catch (err) {
      // Never render a raw FastAPI 422 array — that used to crash this page
      setMessage({ type: 'error', text: friendlyError(err, `Failed to save ${section} settings.`) });
    } finally {
      setSavingSection(null);
    }
  }

  const saveAutomation = (e) => {
    e.preventDefault();
    return withSession('automation', async (accessToken) => {
      await apiFetch('/batteries/me', {
        method: 'PUT',
        accessToken,
        body: { auto_push_enabled: autoPushEnabled },
      });
      // holiday_until is cleared when holiday mode is off or no date is set.
      await apiFetch('/sites/me', {
        method: 'PATCH',
        accessToken,
        body: {
          holiday_mode: holidayMode,
          holiday_until: holidayMode && holidayUntil
            ? new Date(`${holidayUntil}T23:59:59`).toISOString()
            : null,
        },
      });
      setMessage({
        type: 'success',
        text: `Automation saved — auto-push ${autoPushEnabled ? 'ON' : 'OFF'}`
          + `${holidayMode ? ', holiday mode ON' : ''}.`,
      });
    });
  };

  const saveBattery = (e) => {
    e.preventDefault();
    return withSession('battery', async (accessToken) => {
      await apiFetch('/batteries/me', {
        method: 'PUT',
        accessToken,
        body: {
          capacity_kwh: parseFloat(capacityKwh) || 5.0,
          max_charge_kw: parseFloat(maxChargeKw) || 3.0,
          max_discharge_kw: parseFloat(maxDischargeKw) || 3.0,
          min_soc_pct: parseFloat(minSocPct) || 20,
          max_soc_pct: parseFloat(maxSocPct) || 100,
        },
      });
      setMessage({ type: 'success', text: 'Battery settings saved.' });
    });
  };

  const saveCredentials = (e) => {
    e.preventDefault();
    return withSession('credentials', async (accessToken) => {
      const credBody = {};
      if (solcastApiKey) credBody.solcast_api_key = solcastApiKey;
      if (solcastSystemId) credBody.solcast_system_id = solcastSystemId;
      if (foxessApiKey) credBody.foxess_api_key = foxessApiKey;
      if (foxessDeviceSn) credBody.foxess_device_sn = foxessDeviceSn;
      if (octopusApiKey) credBody.octopus_api_key = octopusApiKey;
      if (octopusAccountNumber) credBody.octopus_account_number = octopusAccountNumber;

      await apiFetch('/batteries/me/provider_config', {
        method: 'PUT',
        accessToken,
        body: credBody,
      });
      setMessage({ type: 'success', text: 'API credentials saved.' });
    });
  };

  const Toggle = ({ checked, onChange }) => (
    <label style={styles.toggle}>
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} style={styles.toggleInput} />
      <span style={{ ...styles.toggleSlider, backgroundColor: checked ? '#C3F53C' : '#202938' }}>
        <span style={{ ...styles.toggleKnob, transform: checked ? 'translateX(22px)' : 'translateX(2px)' }} />
      </span>
    </label>
  );

  if (loading) {
    return (
      <div style={styles.container}>
        <p style={styles.loading}>Loading…</p>
      </div>
    );
  }

  return (
    <div style={styles.container}>
      <div style={styles.navRow}>
        <a href="/" style={styles.backLink}>← Dashboard</a>
        <h1 style={styles.title}>Settings</h1>
      </div>

      {message && (
        <div style={{
          ...styles.message,
          backgroundColor: message.type === 'success' ? 'rgba(52,211,153,0.10)' : 'rgba(248,113,113,0.10)',
          color: message.type === 'success' ? '#6EE7B7' : '#FCA5A5',
          borderColor: message.type === 'success' ? 'rgba(52,211,153,0.32)' : 'rgba(248,113,113,0.32)',
        }}>
          {message.text}
        </div>
      )}

      {/* 1. Automation — auto-push + holiday mode, separate from credentials */}
      <form onSubmit={saveAutomation} style={styles.card}>
        <h2 style={{ ...styles.sectionTitle, marginTop: 0 }}>Automation</h2>

        <div style={styles.toggleRow}>
          <div style={styles.toggleInfo}>
            <label style={styles.label}>Auto-push schedule to inverter</label>
            <p style={styles.toggleHint}>
              When on, your optimised schedule is pushed to your FoxESS inverter automatically every 30 minutes
              through the day. You get an alert if a push fails or stops.
            </p>
          </div>
          <Toggle checked={autoPushEnabled} onChange={setAutoPushEnabled} />
        </div>

        <div style={styles.toggleRow}>
          <div style={styles.toggleInfo}>
            <label style={styles.label}>Holiday mode (household away)</label>
            <p style={styles.toggleHint}>
              The demand forecast drops to baseload (fridge, router, standby) instead of your usual routine.
              Anything you schedule on the Events page is still included.
            </p>
          </div>
          <Toggle checked={holidayMode} onChange={setHolidayMode} />
        </div>

        {holidayMode && (
          <div style={{ marginTop: '4px' }}>
            <label style={styles.label}>Return date (optional)</label>
            <input type="date" value={holidayUntil} onChange={(e) => setHolidayUntil(e.target.value)} style={styles.input} />
            <p style={styles.toggleHint}>Turns holiday mode off after this date. Leave blank to keep it on until you switch it off.</p>
          </div>
        )}

        <button type="submit" disabled={savingSection === 'automation'} style={{ ...styles.button, opacity: savingSection === 'automation' ? 0.6 : 1 }}>
          {savingSection === 'automation' ? 'Saving…' : 'Save automation settings'}
        </button>
      </form>

      {/* 2. Battery configuration */}
      <form onSubmit={saveBattery} style={styles.card}>
        <h2 style={{ ...styles.sectionTitle, marginTop: 0 }}>Battery</h2>

        <div style={styles.row}>
          <div style={styles.halfField}>
            <label style={styles.label}>Capacity (kWh)</label>
            <input type="number" step="0.1" value={capacityKwh} onChange={(e) => setCapacityKwh(e.target.value)} style={styles.input} />
          </div>
          <div style={styles.halfField}>
            <label style={styles.label}>Max Charge (kW)</label>
            <input type="number" step="0.1" value={maxChargeKw} onChange={(e) => setMaxChargeKw(e.target.value)} style={styles.input} />
          </div>
        </div>

        <div style={styles.row}>
          <div style={styles.halfField}>
            <label style={styles.label}>Max Discharge (kW)</label>
            <input type="number" step="0.1" value={maxDischargeKw} onChange={(e) => setMaxDischargeKw(e.target.value)} style={styles.input} />
          </div>
          <div style={styles.halfField}>
            <label style={styles.label}>Min SOC (%)</label>
            <input type="number" step="1" value={minSocPct} onChange={(e) => setMinSocPct(e.target.value)} style={styles.input} />
          </div>
        </div>

        <div style={styles.row}>
          <div style={styles.halfField}>
            <label style={styles.label}>Max SOC (%)</label>
            <input type="number" step="1" value={maxSocPct} onChange={(e) => setMaxSocPct(e.target.value)} style={styles.input} />
          </div>
          <div style={styles.halfField} />
        </div>

        <button type="submit" disabled={savingSection === 'battery'} style={{ ...styles.button, opacity: savingSection === 'battery' ? 0.6 : 1 }}>
          {savingSection === 'battery' ? 'Saving…' : 'Save battery settings'}
        </button>
      </form>

      {/* 3. API credentials */}
      <form onSubmit={saveCredentials} style={styles.card}>
        <h2 style={{ ...styles.sectionTitle, marginTop: 0 }}>API Credentials</h2>
        <p style={{ ...styles.toggleHint, marginBottom: '4px' }}>
          Stored encrypted. Used by the background fetchers to pull your solar forecast, usage history and heat-pump data.
        </p>

        <label style={styles.label}>Solcast API Key</label>
        <input type="password" value={solcastApiKey} onChange={(e) => setSolcastApiKey(e.target.value)} placeholder="Your Solcast API key" style={styles.input} />

        <label style={styles.label}>Solcast PV System ID</label>
        <input type="text" value={solcastSystemId} onChange={(e) => setSolcastSystemId(e.target.value)} placeholder="e.g. 7a6e5f2e-..." style={styles.input} />

        <label style={styles.label}>FoxESS API Key (Token)</label>
        <input type="password" value={foxessApiKey} onChange={(e) => setFoxessApiKey(e.target.value)} placeholder="Your FoxESS API token" style={styles.input} />

        <label style={styles.label}>FoxESS Device Serial Number</label>
        <input type="text" value={foxessDeviceSn} onChange={(e) => setFoxessDeviceSn(e.target.value)} placeholder="Your FoxESS device SN" style={styles.input} />

        <label style={styles.label}>Octopus Developer API Key</label>
        <input type="password" value={octopusApiKey} onChange={(e) => setOctopusApiKey(e.target.value)} placeholder="sk_live_..." style={styles.input} />

        <label style={styles.label}>Octopus Account Number</label>
        <input type="text" value={octopusAccountNumber} onChange={(e) => setOctopusAccountNumber(e.target.value)} placeholder="e.g. A-1234ABCD" style={styles.input} />

        <button type="submit" disabled={savingSection === 'credentials'} style={{ ...styles.button, opacity: savingSection === 'credentials' ? 0.6 : 1 }}>
          {savingSection === 'credentials' ? 'Saving…' : 'Save credentials'}
        </button>
      </form>
    </div>
  );
}

const styles = {
  container: {
    minHeight: '100vh',
    background: '#0B0F17',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: '20px',
    padding: '40px 20px 60px',
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
  },
  navRow: {
    maxWidth: '520px',
    width: '100%',
    display: 'flex',
    alignItems: 'center',
    gap: '16px',
  },
  backLink: {
    color: '#8B95A7',
    fontSize: '14px',
    textDecoration: 'none',
  },
  card: {
    background: '#121826',
    border: '1px solid #202938',
    borderRadius: '14px',
    padding: '28px 32px',
    maxWidth: '520px',
    width: '100%',
    boxSizing: 'border-box',
    boxShadow: '0 1px 2px rgba(0,0,0,0.35), 0 12px 32px rgba(0,0,0,0.35)',
  },
  title: {
    fontSize: '24px',
    fontWeight: '700',
    color: '#E7ECF5',
    margin: 0,
  },
  sectionTitle: {
    fontSize: '16px',
    fontWeight: '600',
    color: '#E7ECF5',
    margin: '24px 0 12px 0',
    paddingBottom: '6px',
    borderBottom: '1px solid #202938',
  },
  label: {
    display: 'block',
    fontSize: '13px',
    fontWeight: '500',
    color: '#8B95A7',
    marginBottom: '4px',
    marginTop: '12px',
  },
  input: {
    width: '100%',
    padding: '10px 12px',
    background: '#171E2A',
    border: '1px solid #202938',
    borderRadius: '6px',
    fontSize: '14px',
    fontFamily: 'monospace',
    color: '#E7ECF5',
    boxSizing: 'border-box',
    outline: 'none',
  },
  button: {
    marginTop: '24px',
    width: '100%',
    padding: '12px',
    background: '#C3F53C',
    color: '#0B0F17',
    border: 'none',
    borderRadius: '8px',
    fontSize: '16px',
    fontWeight: '600',
    cursor: 'pointer',
  },
  message: {
    maxWidth: '520px',
    width: '100%',
    boxSizing: 'border-box',
    padding: '12px 16px',
    borderRadius: '8px',
    border: '1px solid',
    fontSize: '14px',
  },
  loading: {
    color: '#8B95A7',
    marginTop: '80px',
  },
  row: {
    display: 'flex',
    gap: '12px',
  },
  halfField: {
    flex: 1,
  },
  toggleRow: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '12px 0',
  },
  toggleInfo: {
    flex: 1,
    marginRight: '16px',
  },
  toggleHint: {
    fontSize: '12px',
    color: '#5A6376',
    margin: '4px 0 0 0',
    lineHeight: '1.4',
  },
  toggle: {
    position: 'relative',
    display: 'inline-block',
    width: '48px',
    height: '26px',
    flexShrink: 0,
  },
  toggleInput: {
    opacity: 0,
    width: 0,
    height: 0,
  },
  toggleSlider: {
    position: 'absolute',
    cursor: 'pointer',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    borderRadius: '26px',
    transition: '0.3s',
    display: 'flex',
    alignItems: 'center',
  },
  toggleKnob: {
    width: '22px',
    height: '22px',
    backgroundColor: '#E7ECF5',
    borderRadius: '50%',
    boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
    transition: '0.3s',
  },
};
