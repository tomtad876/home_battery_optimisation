from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
from app.api.routes import router

app = FastAPI(title="Energy Optimiser API")

# Configure allowed origins via FRONTEND_ORIGINS env var (comma-separated).
# Example: FRONTEND_ORIGINS="http://localhost:3000,http://10.5.0.2:3000"
raw = os.environ.get("FRONTEND_ORIGINS", "http://localhost:3000,http://localhost:8000")
origins = [o.strip() for o in raw.split(",") if o.strip()]

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
