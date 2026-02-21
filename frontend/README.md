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
NEXT_PUBLIC_API_URL=https://your-api.railway.app
```

### 3. Run Development Server
```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

## Features

- **Battery Configuration Panel** (left sidebar)
  - PV system ID
  - Battery capacity & SOC bounds
  - Power limits (charge/discharge)
  - Export tariff settings

- **Interactive Charts** (right panel)
  - **Solar, Demand & Price** – 3-axis line chart showing forecast trends
  - **State of Charge** – Battery SOC % over time
  - **Battery Actions** – Charge/discharge dispatch decisions
  - **Grid Energy** – Import/export flows
  - **Cumulative Cost** – Running total cost breakdown

- **Summary Cards**
  - Total cost (£)
  - Solar generation (kWh)
  - Total demand (kWh)
  - Export revenue (£)

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

- **React 18.3** – UI framework
- **Next.js 15** – Full-stack framework
- **Recharts 2.12** – Chart library
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
