> **Historical** — This README is outdated. See `projects/business/battery-optimisation.md` for current status and architecture.

# Home Battery Optimisation

A **FastAPI** backend service to optimise battery charge/discharge schedules, paired with a **Next.js** frontend UI for real-time visualisation.

## Architecture

```
Browser (Next.js, Vercel)
   ↓ /optimise/mvp (POST)  /  /optimise/push (POST)
  Python API (FastAPI, Render)
   ↓
├─ Solcast API (solar forecast)
├─ FoxESS API (demand history + Agile prices + battery control)
└─ Supabase Edge Functions (scheduled data fetch + auto-push)
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
- **`POST /optimise/push`** – Classify + push schedule to FoxESS inverter (preview or live)
- **`POST /internal/optimise`** – Service-to-service endpoint for Edge Functions
- **`GET /health`** – Health check
- Multi-tenant auth (Supabase JWT, ES256 + HS256 fallback)
- Encrypted credentials (Fernet AES-128-CBC + HMAC-SHA256)
- Graceful error handling & validation

### Frontend (Next.js + Chart.js)
- Interactive charts: solar, demand, price, SOC, charge/discharge, grid flows, cumulative cost
- Setup wizard (4-step: site → battery → tariff → credentials)
- Settings page: battery config, API credentials, auto-push toggle
- Auth guard: no login → login, no site → wizard, has site → dashboard

### Edge Functions (Supabase)
- `fetch-solcast`, `fetch-agile-prices`, `fetch-demand` — scheduled data collection
- `optimise-and-push` — background cron: fetch SOC → optimise → classify → push to inverter
- Grid-aware classifier: maps optimiser output to FoxESS v3 schedule groups

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
  "discharge_power_kw": 3.0
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

### Backend (Render)

1. **Connect GitHub repo to Render**
2. **Set environment variables:**
   - `SOLCAST_API_KEY`, `FOXESS_API_KEY`
   - `SUPABASE_URL`, `SUPABASE_JWT_SECRET`
   - `INTERNAL_API_KEY` (shared secret for Edge Function calls)
3. **Deploy automatically on push to main**

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
│   ├── api/routes.py            # FastAPI endpoints (/optimise/mvp, /optimise/push, /internal/optimise)
│   ├── core/optimiser.py        # LP solver (CVXPY)
│   ├── services/
│   │   ├── solcast.py           # Solar forecast
│   │   ├── foxess.py            # Demand + Agile prices + classifier
│   │   └── forecast.py          # Combined helpers
│   ├── models/                  # SQLAlchemy ORM
│   ├── schemas/                 # Pydantic models
│   └── main.py                  # FastAPI app
├── tests/                        # pytest suite
├── supabase/
│   ├── functions/
│   │   ├── fetch-solcast/       # Scheduled Solcast fetch
│   │   ├── fetch-agile-prices/  # Scheduled Agile price fetch
│   │   ├── fetch-demand/        # Scheduled demand profile fetch
│   │   ├── optimise-and-push/   # Background optimise + push to inverter
│   │   └── shared/              # Classifier + FoxESS helpers (TS)
│   └── migrations/              # Alembic + Supabase migrations
├── frontend/                     # Next.js UI
│   ├── components/
│   │   ├── OptimiserForm.js     # Parameter form
│   │   └── ScheduleCharts.js    # Chart.js visualisations
│   ├── pages/
│   │   ├── index.js             # Dashboard
│   │   ├── settings.js          # Battery config + credentials
│   │   └── wizard.js            # Setup wizard
│   ├── styles/globals.css       # Tailwind
│   └── package.json
├── alembic/                      # DB migrations
├── requirements.txt             # Python dependencies
└── README.md
```

## Current Scope (live on prod 2026-09-06)

- ✅ **Tariff:** Octopus Agile import + export
- ✅ **Solar:** Solcast 30-min forecasts
- ✅ **Demand:** FoxESS 7-day average (time-of-day profile)
- ✅ **Optimisation:** Linear programming (global optimum, not greedy)
- ✅ **Push:** Classify + push schedule to FoxESS inverter (manual + auto-push cron)
- ✅ **Multi-tenant:** Supabase JWT auth, per-user sites/batteries/credentials
- ✅ **Setup wizard:** 4-step onboarding (site → battery → tariff → credentials)
- ✅ **Settings:** Battery config, API credentials, auto-push toggle
- ✅ **Edge Functions:** Scheduled data fetch + background optimise-and-push

## Known Limitations

- **Demand forecast:** Simple 7-day average. Upgrade to ML (Prophet, LSTM) for better accuracy
- **Tariff:** No support for Economy 7 or other non-Agile tariff structures yet
- **Optimiser:** No battery health degradation or thermal constraints
- **Round-trip efficiency:** Currently ignores charge/discharge losses (planned fix)

## Stack Summary

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Backend | FastAPI + Python 3.13 | API & LP solver |
| Optimisation | CVXPY | Convex optimisation |
| Frontend | Next.js 15 + React 18 | Interactive UI |
| Charts | Recharts | Data visualisation |
| Styling | Tailwind CSS 3.4 | Utility-first CSS |
| Testing | pytest 9.0 | Backend unit & integration tests |
| Deployment | Render/Vercel/Supabase | Production hosting |

---

**Source of truth:** `projects/business/battery-optimisation.md`
