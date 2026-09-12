> **Historical** — This README is outdated. See `projects/business/battery-optimisation.md` for current features.

# Battery Optimiser UI

A Next.js frontend for visualizing battery optimisation schedules from the backend API.

## Quick Start

### 1. Install Dependencies
```bash
cd frontend
npm install
```

### 2. Configure API URL
Edit `.env.local` to point to your backend:
```
NEXT_PUBLIC_API_URL=http://localhost:8000
```

For production (Vercel):
```
NEXT_PUBLIC_API_URL=https://home-battery-optimisation.onrender.com
```

### 3. Run Development Server
```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

## Features

- **Auth**: Supabase JWT login (ES256 + HS256 fallback)
- **Setup Wizard**: 4-step onboarding (site → battery → tariff → credentials)
- **Dashboard**: Interactive charts (solar, demand, price, SOC, charge/discharge, grid flows, cumulative cost)
- **Settings**: Battery config (capacity, power, SOC), API credentials (encrypted), auto-push toggle
- **Preview**: Run optimiser + classifier without pushing to inverter

## Architecture

```
frontend/
├── components/
│   ├── OptimiserForm.js      # Parameter input form
│   └── ScheduleCharts.js     # Recharts visualisations
├── pages/
│   ├── index.js              # Main page
│   └── _document.js          # App wrapper
├── styles/
│   └── globals.css           # Tailwind CSS
├── package.json
├── next.config.js
└── tailwind.config.js
```

## Dependencies

- **React 18** – UI framework
- **Next.js 15** – Full-stack framework
- **Chart.js** – Chart library
- **Tailwind CSS 3.4** – Utility-first styling

## Deployment

### Vercel (Recommended)
```bash
vercel deploy
# Set NEXT_PUBLIC_API_URL environment variable in Vercel dashboard
```

### Manual Deployment
```bash
npm run build
npm run start
```

## Development

- Hot reload via `npm run dev`
- Build for production: `npm run build`
- Lint code: `npm run lint`

## Notes

- Backend must be running for API calls to work
- CORS must be enabled on backend (or requests must be proxied)
- Charts auto-aggregate 30-min data into hourly for readability
