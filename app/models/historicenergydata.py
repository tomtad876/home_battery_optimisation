import uuid
from sqlalchemy import Column, DateTime, Float, String, UniqueConstraint, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base

class HistoricEnergyData(Base):
    __tablename__ = "historic_energy_data"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    period_end = Column(DateTime, nullable=False)
    variable = Column(String, nullable=True)
    unit = Column(String, nullable=True)
    name = Column(String, nullable=True)
    value = Column(Float, nullable=True)
    time = Column(String, nullable=True)
    site_id = Column(UUID(as_uuid=True), ForeignKey("sites.id"), nullable=True)

    __table_args__ = (
        UniqueConstraint('period_end', 'variable', name='uq_period_variable'),
    )

