import uuid
from sqlalchemy import Column, DateTime, Float, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from app.core.database import Base

# Register `sites` so the FKs resolve (the data layer is otherwise raw SQL).
from app.models.site import Site  # noqa: F401


class HeatPump(Base):
    """A heat-pump controller discovered via the Octopus API (per site)."""

    __tablename__ = "heat_pumps"
    __table_args__ = (UniqueConstraint("site_id", "euid", name="uq_heat_pumps_site_euid"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id = Column(UUID(as_uuid=True), ForeignKey("sites.id"), nullable=False)
    euid = Column(String, nullable=False)
    property_id = Column(String, nullable=True)
    model = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))


class HeatPumpData(Base):
    """One Octopus heat-pump poll.

    `power_input_kw`/`heat_output_kw`/`cop`/`outdoor_temp_c` are live snapshots;
    `lifetime_*` are cumulative counters, so the delta between consecutive rows
    is the energy used in that interval.
    """

    __tablename__ = "heat_pump_data"
    __table_args__ = (UniqueConstraint("site_id", "read_at", name="uq_heat_pump_data_site_read_at"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id = Column(UUID(as_uuid=True), ForeignKey("sites.id"), nullable=False)
    read_at = Column(DateTime(timezone=True), nullable=False)
    power_input_kw = Column(Float, nullable=True)
    heat_output_kw = Column(Float, nullable=True)
    cop = Column(Float, nullable=True)
    outdoor_temp_c = Column(Float, nullable=True)
    lifetime_energy_input_kwh = Column(Float, nullable=True)
    lifetime_heat_output_kwh = Column(Float, nullable=True)
    lifetime_scop = Column(Float, nullable=True)
    water_mode = Column(String, nullable=True)
    water_setpoint_c = Column(Float, nullable=True)
    zones = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
