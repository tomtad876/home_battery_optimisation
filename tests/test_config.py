"""Tests for settings normalisation."""
from app.core.config import normalise_db_url


class TestNormaliseDbUrl:
    """A bare postgres URL must be pinned to psycopg2 (SQLAlchemy 2.1 regression)."""

    def test_plain_postgresql_gets_psycopg2(self):
        assert normalise_db_url("postgresql://u:p@h:5432/db") == "postgresql+psycopg2://u:p@h:5432/db"

    def test_legacy_postgres_scheme(self):
        assert normalise_db_url("postgres://u@h/db") == "postgresql+psycopg2://u@h/db"

    def test_psycopg3_scheme_is_rewritten(self):
        assert normalise_db_url("postgresql+psycopg://u@h/db") == "postgresql+psycopg2://u@h/db"

    def test_already_psycopg2_untouched(self):
        assert normalise_db_url("postgresql+psycopg2://u@h/db") == "postgresql+psycopg2://u@h/db"

    def test_non_postgres_and_empty_untouched(self):
        assert normalise_db_url("sqlite:///x.db") == "sqlite:///x.db"
        assert normalise_db_url(None) is None
        assert normalise_db_url("") == ""
