import os
from dotenv import load_dotenv

load_dotenv()


def normalise_db_url(url: str | None) -> str | None:
    """Force the psycopg2 driver onto a PostgreSQL URL.

    SQLAlchemy 2.1 changed the default PostgreSQL DBAPI from psycopg2 to
    psycopg (v3). A bare ``postgresql://`` URL then makes SQLAlchemy import
    ``psycopg``, which we don't ship (we install ``psycopg2-binary``), so the app
    crashed at import on Render while working locally on SQLAlchemy 2.0.

    Pinning the driver in the URL makes it unambiguous on any SQLAlchemy
    version. Non-PostgreSQL URLs (e.g. sqlite in tests) are left untouched.
    """
    if not url:
        return url
    for prefix in ("postgres://", "postgresql://", "postgresql+psycopg://"):
        if url.startswith(prefix):
            return "postgresql+psycopg2://" + url[len(prefix):]
    return url


class Settings:
    DATABASE_URL: str = normalise_db_url(os.getenv("DATABASE_URL"))
    # Error monitoring. Optional: when SENTRY_DSN is unset the SDK is never
    # initialised, so local dev and tests are unaffected. Environment defaults
    # to "production" so Render errors are distinguishable from local ones.
    SENTRY_DSN: str | None = os.getenv("SENTRY_DSN")
    SENTRY_ENVIRONMENT: str = os.getenv("SENTRY_ENVIRONMENT", "production")
    # Trace sampling; 0 by default (errors only). Raising it adds request spans.
    SENTRY_TRACES_SAMPLE_RATE: float = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0"))


settings = Settings()
