from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
from app.api.routes import router

app = FastAPI(title="Energy Optimiser API")

# Configure allowed origins via FRONTEND_ORIGINS env var (comma-separated).
# Example: FRONTEND_ORIGINS="http://localhost:3000,http://10.5.0.2:3000"
raw = os.environ.get("FRONTEND_ORIGINS", "http://localhost:3000,http://localhost:8000,http://10.5.0.2:3000,https://home-battery-optimisation.vercel.app")
origins = [o.strip() for o in raw.split(",") if o.strip()]

# Vercel gives every branch preview its own hostname
# (home-battery-optimisation-git-<branch>-<team>.vercel.app), so an allowlist of
# exact origins can never cover them — a preview deployment gets its preflight
# rejected and every API call fails as a CORS error in the browser. Allow this
# project's own preview hosts by pattern (deliberately not *.vercel.app, which
# would allow anyone's deployment). Override/disable with FRONTEND_ORIGIN_REGEX.
origin_regex = os.environ.get(
    "FRONTEND_ORIGIN_REGEX",
    r"https://home-battery-optimisation-[a-z0-9-]+\.vercel\.app",
)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_origin_regex=origin_regex or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
