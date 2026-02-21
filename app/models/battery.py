from sqlalchemy import Column, Float, ForeignKey, String, JSON
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base

class Battery(Base):
    __tablename__ = "batteries"

    id = Column(UUID(as_uuid=True), primary_key=True)
    site_id = Column(UUID(as_uuid=True), ForeignKey("sites.id"))
    
    capacity_kwh = Column(Float, nullable=False)
    max_charge_kw = Column(Float, nullable=False)
    max_discharge_kw = Column(Float, nullable=False)
    
    min_soc_pct = Column(Float, nullable=False)
    max_soc_pct = Column(Float, nullable=False)

    provider_type = Column(String, nullable=False)
    provider_config = Column(JSON, nullable=True)