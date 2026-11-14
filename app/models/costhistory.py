"""Cost history: per-day savings and the tariff history used to price them."""
import uuid

from sqlalchemy import JSON, Column, Date, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class SiteTariffHistory(Base):
    """What the site was actually paying, period by period.

    The ``tariffs`` table holds only the current choice, which is not enough to
    price history: export changed from 12p fixed to Agile Outgoing mid-August
    2026, and import from Agile to Cosy in November. Each row is a period.
    """

    __tablename__ = "site_tariff_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id = Column(UUID(as_uuid=True), ForeignKey("sites.id", ondelete="CASCADE"), nullable=False)
    valid_from = Column(DateTime(timezone=True), nullable=False)
    valid_to = Column(DateTime(timezone=True), nullable=True)
    import_type = Column(String, nullable=False)
    import_config = Column(JSON, nullable=False, server_default=text("'{}'::json"))
    export_type = Column(String, nullable=False)
    export_config = Column(JSON, nullable=False, server_default=text("'{}'::json"))
    note = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("site_id", "valid_from", name="uq_site_tariff_history_from"),
    )


class DailyCostSummary(Base):
    """One row per site per local day. All money is GBP, inc VAT."""

    __tablename__ = "daily_cost_summary"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id = Column(UUID(as_uuid=True), ForeignKey("sites.id", ondelete="CASCADE"), nullable=False)
    day = Column(Date, nullable=False)

    import_kwh = Column(Float, nullable=False, server_default="0")
    export_kwh = Column(Float, nullable=False, server_default="0")
    pv_kwh = Column(Float, nullable=False, server_default="0")
    load_kwh = Column(Float, nullable=False, server_default="0")

    import_cost_gbp = Column(Float, nullable=False, server_default="0")
    export_income_gbp = Column(Float, nullable=False, server_default="0")
    standing_gbp = Column(Float, nullable=False, server_default="0")
    net_cost_gbp = Column(Float, nullable=False, server_default="0")

    nokit_cost_gbp = Column(Float, nullable=False, server_default="0")
    solar_only_cost_gbp = Column(Float, nullable=False, server_default="0")
    selfuse_cost_gbp = Column(Float, nullable=False, server_default="0")

    solar_value_gbp = Column(Float, nullable=False, server_default="0")
    battery_value_gbp = Column(Float, nullable=False, server_default="0")
    optimiser_value_gbp = Column(Float, nullable=False, server_default="0")
    total_value_gbp = Column(Float, nullable=False, server_default="0")

    soc_min_pct = Column(Float, nullable=True)
    soc_max_pct = Column(Float, nullable=True)
    covered_slots = Column(Integer, nullable=False, server_default="0")
    expected_slots = Column(Integer, nullable=False, server_default="48")
    source = Column(String, nullable=False, server_default="foxess")
    computed_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("site_id", "day", name="uq_daily_cost_summary_site_day"),
    )
