"""JWT verification for Supabase Auth tokens."""
import os
import json
import urllib.request
from pathlib import Path
from functools import lru_cache
import jwt
from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://zkvnngijbostksjhkkdf.supabase.co")

security = HTTPBearer()


@lru_cache(maxsize=1)
def _fetch_jwks() -> dict:
    """Fetch and cache the Supabase JWKS (public keys for ES256 verification)."""
    url = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read())


def _get_signing_key(token: str):
    """Return the appropriate key for verifying the token (ES256 public key or HS256 secret)."""
    # Decode header only (no verification)
    unverified = jwt.get_unverified_header(token)
    alg = unverified.get("alg")
    kid = unverified.get("kid")

    if alg == "ES256":
        jwks = _fetch_jwks()
        for key_data in jwks.get("keys", []):
            if key_data.get("kid") == kid:
                return jwt.PyJWK(key_data)
        raise ValueError(f"Unknown kid: {kid}")

    # Fallback to HS256 legacy secret
    if SUPABASE_JWT_SECRET:
        return SUPABASE_JWT_SECRET

    raise ValueError("No signing key available")


def verify_token(cred: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """FastAPI dependency: verify Supabase JWT and return the payload."""
    token = cred.credentials
    try:
        signing_key = _get_signing_key(token)
        if isinstance(signing_key, jwt.PyJWK):
            payload = jwt.decode(token, signing_key.key, algorithms=["ES256"], options={"verify_aud": False})
        else:
            payload = jwt.decode(token, signing_key, algorithms=["HS256"], options={"verify_aud": False})
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
