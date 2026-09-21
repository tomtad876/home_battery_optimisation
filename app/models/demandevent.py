import uuid
from sqlalchemy import Column, Date, DateTime, Float, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from app.core.database import Base

# Register the `sites` table in SQLAlchemy's metadata so the FK below resolves.
# The app's data layer is otherwise raw SQL (data_provider.py), so `Site` is not
# imported anywhere else and the FK would otherwise raise NoReferencedTableError.
from app.models.site import Site  # noqa: F401


class DemandEvent(Base):
    """A labelled appliance/activity event on household demand.

    `appliance` is a free-form tag ('cosy', 'washing_machine', 'tumble_dryer',
    'dishwasher', 'oven', 'heating', 'gaming', 'other', 'combined', ...).
    `start_time`/`end_time` are tz-aware; the frontend converts local time to UTC.

    `cleanliness` is the template-fitting filter: 'clean' (nothing else running),
    'unsure', 'contaminated' (other appliances overlapping). NULL = not yet
    annotated. `target_temp`/`start_temp` capture the heat-pump DHW setpoint and
    tank start temperature — the Cosy is a function of temperature lift, not a
    fixed template.
    """

    __tablename__ = "demand_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id = Column(UUID(as_uuid=True), ForeignKey("sites.id"), nullable=False)
    appliance = Column(String, nullable=False)
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=True)
    status = Column(String, nullable=False, server_default="confirmed")  # planned/confirmed/cancelled
    energy_kwh = Column(Float, nullable=True)
    source = Column(String, nullable=False, server_default="manual")  # manual/routine/inferred
    cleanliness = Column(String, nullable=True)  # clean/unsure/contaminated
    target_temp = Column(Float, nullable=True)
    start_temp = Column(Float, nullable=True)
    notes = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))


class DemandDayInventory(Base):
    """A per-day "what ran today" tick-list (set-level supervision label).

    Gives labels *with negatives*: a day whose inventory is a single appliance
    makes every detected window that day provably clean. `day` is a local
    (Europe/London) calendar date; `appliances` is the set of appliance tags
    used that day.
    """

    __tablename__ = "demand_day_inventory"
    __table_args__ = (UniqueConstraint("site_id", "day", name="uq_demand_day_inventory_site_day"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id = Column(UUID(as_uuid=True), ForeignKey("sites.id"), nullable=False)
    day = Column(Date, nullable=False)
    appliances = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    notes = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))
