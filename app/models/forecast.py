import uuid
from sqlalchemy import Column, DateTime, Float, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base

class ForecastRun(Base):
    __tablename__ = "forecast_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id = Column(UUID(as_uuid=True), ForeignKey("sites.id"))
    run_time = Column(DateTime, nullable=False)

class ForecastInterval(Base):
    __tablename__ = "forecast_intervals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    forecast_run_id = Column(UUID(as_uuid=True), ForeignKey("forecast_runs.id"))

    period_end = Column(DateTime, nullable=False)
    solar_kwh = Column(Float, nullable=False)
    demand_kwh = Column(Float, nullable=False)
    import_price = Column(Float, nullable=False)
    export_price = Column(Float, nullable=False)