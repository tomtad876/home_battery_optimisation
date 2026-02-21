# How to Run Backend + Frontend Locally

## Prerequisites
- Python 3.11+ 
- Node.js 18+
- Terminal/command line access
- Valid environment variables (SOLCAST_API_KEY, FOXESS_API_KEY)

## Step 1: Start Backend (Port 8000)

```bash
# From project root
cd c:\Users\Thoma\PycharmProjects\home_battery_optimisation

# Create/activate venv (if not already done)
python -m venv venv
venv\Scripts\activate

# Install deps
pip install -r requirements.txt

# Run API server
uvicorn app.main:app --reload --port 8000
```

**Output should say:** `Uvicorn running on http://127.0.0.1:8000`

Test it works:
```bash
curl http://localhost:8000/health
# Should return: {"status":"ok"}
```

## Step 2: Start Frontend (Port 3000)

Open a **new terminal**:

```bash
# From project root
cd c:\Users\Thoma\PycharmProjects\home_battery_optimisation\frontend

# Install deps
npm install

# Run dev server
npm run dev
```

**Output should say:** `▲ Next.js [version]  ready on http://localhost:3000`

## Step 3: Open Browser

Navigate to **http://localhost:3000**

You should see:
- Left panel: Battery configuration form
- Right panel: (empty until you optimise)

## Step 4: Configure & Test

### Fill in the form:
1. **PV System ID** – Enter your Solcast PV system ID (e.g. `feae-7d5c-b618-0bfa`)
2. **Battery Capacity** – Keep at 15 kWh (or adjust to your battery)
3. **Initial SOC** – Set to current battery state (e.g. 50%)
4. **SOC Bounds** – Min 20%, Max 90% (default, adjust if needed)
5. **Power Limits** – Charge/discharge power (default 3 kW each)
6. **Export Price** – 15p/kWh (standard for flat export in UK)

### Click "Optimise"

The frontend will:
1. Send parameters to `http://localhost:8000/optimise/mvp`
2. Receive 48-hour schedule with optimal battery dispatch
3. Draw 5 charts showing:
   - Solar/demand/price trends
   - Battery SOC over time
   - Charge/discharge actions
   - Grid import/export flows
   - Cumulative cost

You should see summary cards with:
- **Total Cost** (£)
- **Grid Export Revenue** (£)
- **Solar Generation** (kWh)
- **Total Demand** (kWh)

## Troubleshooting

### "Cannot POST /optimise/mvp"
- Ensure backend is running on port 8000
- Check `.env` has valid SOLCAST_API_KEY and FOXESS_API_KEY

### "PvEstimate is missing" or "demand is missing"
- Check your Solcast API key and PV system ID are valid
- FoxESS load history might be empty (needs 7+ days of data)

### CORS error on frontend
- Backend CORS is enabled by default (localhost:3000 is whitelisted)
- If different port, add to CORSMiddleware in `app/main.py`

### Chart doesn't show
- Schedule data exists but rendering might fail if empty
- Check browser console (F12 → Console) for JavaScript errors

### Port 8000/3000 already in use
```bash
# Free port 8000 (Windows)
netsh int ipv4 show tcpconn | findstr 8000
taskkill /PID [PID] /F

# Or use different port
uvicorn app.main:app --reload --port 8001
# Then update frontend .env.local: NEXT_PUBLIC_API_URL=http://localhost:8001
```

## Running Tests

```bash
# All tests
pytest

# Verbose output
pytest -v

# Watch mode (auto-rerun on file changes)
pytest-watch
```

Should see: **23 passed in ~2s**

## Next: Prepare for Production

### Backend Deployment (Railway/Fly)
See [NEXT_STEPS.md](NEXT_STEPS.md)

### Frontend Deployment (Vercel)
```bash
cd frontend
npm run build
vercel deploy
# Set NEXT_PUBLIC_API_URL in Vercel dashboard
```

---

**That's it!** You're running the full battery optimiser stack locally. 🚀
