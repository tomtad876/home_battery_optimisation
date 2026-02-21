# Home Battery Optimisation – MVP Backend + Frontend

A **FastAPI** backend service to optimise battery charge/discharge schedules, paired with a **Next.js** frontend UI for real-time visualisation.

## Architecture

```
Browser (Next.js, Vercel)
   ↓ /optimise/mvp (POST)
  Python API (FastAPI, Railway/Fly)
   ↓
├─ Solcast API (solar forecast)
└─ FoxESS API (demand history + Agile prices + battery control)
```

## Quick Start (Full Stack)

### Backend Setup

1. **Install Python Dependencies**
```bash
pip install -r requirements.txt
```

2. **Configure Environment**
```bash
cp .env.example .env
# Fill in: SOLCAST_API_KEY, FOXESS_API_KEY
```

3. **Run API Server**
```bash
uvicorn app.main:app --reload --port 8000
```

✅ API available at `http://localhost:8000`

### Frontend Setup

1. **Install Node Dependencies**
```bash
cd frontend
npm install
```

2. **Configure API URL** (optional, defaults to localhost:8000)
```bash
# Edit frontend/.env.local if using different backend URL
NEXT_PUBLIC_API_URL=http://localhost:8000
```

3. **Run Development Server**
```bash
npm run dev
```

✅ UI available at `http://localhost:3000`

## Features

### Backend (Python FastAPI)
- **`POST /optimise/mvp`** – Compute optimal battery dispatch (LP solver using CVXPY)
- **`GET /health`** – Health check
- 23 comprehensive pytest tests
- Graceful error handling & validation

### Frontend (Next.js + Recharts)
- 📊 **5 Interactive Charts**:
  - Solar, demand, price trends
  - Battery state of charge (SOC)
  - Charge/discharge decisions
  - Grid import/export flows
  - Cumulative cost tracking
- ⚙️ **Parameter Control Panel**
  - Battery capacity, SOC bounds
  - Power limits, tariff settings
  - Real-time form validation
- 💾 **Summary Statistics**
  - Total cost, solar generation
  - Grid energy flows

## API Endpoints

### `POST /optimise/mvp`
Optimise battery dispatch schedule for lowest cost over 24-48 hours.

**Request:**
```json
{
  "pv_system_id": "feae-7d5c-b618-0bfa",
  "battery_capacity_kwh": 15.0,
  "initial_soc_pct": 50.0,
  "min_soc_pct": 20.0,
  "max_soc_pct": 90.0,
  "charge_power_kw": 3.0,
  "discharge_power_kw": 3.0,
  "export_price_pence": 15.0
}
```

**Response:**
```json
{
  "status": "success",
  "generated_at": "2025-09-20T18:30:00Z",
  "summary": {
    "total_cost_gbp": 2.15,
    "total_solar_kwh": 12.3,
    "total_demand_kwh": 18.5,
    "total_grid_import_kwh": 8.2,
    "total_grid_export_kwh": 2.0
  },
  "schedule": [
    {
      "PeriodEnd": "2025-09-20T19:00:00Z",
      "demand": 0.8,
      "solar": 0.0,
      "price": 25.5,
      "batt_charge_kwh": 0.0,
      "batt_discharge_kwh": 0.7,
      "grid_import_kwh": 0.0,
      "grid_export_kwh": 0.1,
      "soc_kwh": 7.3,
      "soc_pct": 48.7,
      "net_battery_kwh": -0.7,
      "cost_gbp": -0.015
    },
    ...
  ]
}
```

## Testing

### Run All Tests
```bash
pytest -v
```

### Test Coverage
```bash
pytest --cov=app --cov-report=html
```

### Test Modules
- `tests/test_optimiser.py` – LP solver logic (7 tests)
- `tests/test_services.py` – API integrations (9 tests)
- `tests/test_routes.py` – FastAPI endpoints (7 tests)

## Deployment

### Backend (Railway / Fly.io)

1. **Create Railway/Fly project**
2. **Set environment variables:**
   - `SOLCAST_API_KEY`
   - `FOXESS_API_KEY`
3. **Deploy:**
   ```bash
   railway deploy  # Railway
   # or
   flyctl deploy   # Fly.io
   ```

### Frontend (Vercel)

1. **Connect GitHub repo to Vercel**
2. **Set root directory to `frontend/`**
3. **Set environment variable:**
   - `NEXT_PUBLIC_API_URL=https://your-api.railway.app`
4. **Deploy automatically on push**

## File Structure

```
home_battery_optimisation/
├── app/                          # Backend API
│   ├── api/routes.py            # FastAPI endpoints
│   ├── core/optimiser.py        # LP solver (CVXPY)
│   ├── services/
│   │   ├── solcast.py           # Solar forecast
│   │   ├── foxess.py            # Demand + Agile prices
│   │   └── forecast.py          # Combined helpers
│   ├── models/                  # SQLAlchemy ORM
│   ├── schemas/                 # Pydantic models
│   └── main.py                  # FastAPI app
├── tests/                        # pytest suite
├── frontend/                     # Next.js UI
│   ├── components/
│   │   ├── OptimiserForm.js     # Parameter form
│   │   └── ScheduleCharts.js    # Recharts visualisations
│   ├── pages/
│   │   ├── index.js             # Main page
│   │   └── _document.js         # App wrapper
│   ├── styles/globals.css       # Tailwind
│   └── package.json
├── requirements.txt             # Python dependencies
└── README.md
```

## MVP Scope

- ✅ **Tariff:** Octopus Agile import + 15p flat export
- ✅ **Solar:** Solcast 30-min forecasts
- ✅ **Demand:** FoxESS 7-day average (time-of-day profile)
- ✅ **Optimisation:** Linear programming (global optimum, not greedy)
- ✅ **UI:** Interactive dashboard with 5 charts + parameter controls
- ✅ **Testing:** 23 comprehensive tests + 100% API coverage

## Known Limitations

- **Demand forecast:** Simple 7-day average. Upgrade to ML (Prophet, LSTM) for better accuracy
- **Tariff:** Hardcoded 15p export. No support for Economy 7 or dynamic peak/off-peak yet
- **Optimiser:** No battery health degradation or thermal constraints
- **No V2G:** Vehicle-to-grid not supported (future feature)

## Next Steps

### Phase 2: Production Hardening
- [ ] Persistent storage (save optimisation runs to DB)
- [ ] User authentication & multi-site support
- [ ] `/schedule/send` endpoint (program battery directly)
- [ ] Webhook notifications on price spikes
- [ ] Historical run comparison

### Phase 3: Advanced Forecasting
- [ ] ML demand model (Prophet/LSTM)
- [ ] Weather integration for solar
- [ ] Octopus regional pricing

### Phase 4: Optimisation Upgrades
- [ ] Dynamic tariff support (Economy 7)
- [ ] Battery degradation modeling
- [ ] Stochastic optimisation (handle forecast uncertainty)
- [ ] MPC (Model Predictive Control) with receding horizon

## Stack Summary

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Backend | FastAPI + Python 3.13 | API & LP solver |
| Optimisation | CVXPY | Convex optimisation |
| Frontend | Next.js 15 + React 18 | Interactive UI |
| Charts | Recharts | Data visualisation |
| Styling | Tailwind CSS 3.4 | Utility-first CSS |
| Testing | pytest 9.0 | Backend unit & integration tests |
| Deployment | Railway/Vercel | Production hosting |

---

For API details, see [app/README.md](app/README.md).
For UI setup, see [frontend/README.md](frontend/README.md).
