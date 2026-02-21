import uuid
from sqlalchemy import Column, DateTime, Float
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base

class SolcastForecast(Base):
    __tablename__ = "solcast_forecast"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    period_end = Column(DateTime, nullable=False, unique=True)
    solar_kwh = Column(Float, nullable=False)
