import uuid
from sqlalchemy import Column, Float, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base

class OptimisationRun(Base):
    __tablename__ = "optimisation_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id = Column(UUID(as_uuid=True), ForeignKey("sites.id"))
    forecast_run_id = Column(UUID(as_uuid=True), ForeignKey("forecast_runs.id"))

    initial_soc_kwh = Column(Float, nullable=False)
    total_cost_estimate = Column(Float)
    status = Column(String, default="pending")

class OptimisationInterval(Base):
    __tablename__ = "optimisation_intervals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    optimisation_run_id = Column(UUID(as_uuid=True), ForeignKey("optimisation_runs.id"))

    period_end = Column(DateTime, nullable=False)
    charge_kwh = Column(Float)
    discharge_kwh = Column(Float)
    soc_kwh = Column(Float)
    grid_import_kwh = Column(Float)
    grid_export_kwh = Column(Float)
    cost = Column(Float)