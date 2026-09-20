import uuid
from sqlalchemy import Column, DateTime, Float, String, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base


class DemandEvent(Base):
    """A labelled appliance/activity event on household demand.

    `appliance` is a free-form tag ('cosy', 'washing_machine', 'tumble_dryer',
    'dishwasher', 'oven', 'heating', 'gaming', 'other', ...). `start_time`/
    `end_time` are tz-aware; the frontend converts local time to UTC.
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
    notes = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))
