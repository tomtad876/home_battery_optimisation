import uuid
from sqlalchemy import Column, DateTime, Float
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base

class AgileRate(Base):
    __tablename__ = "agile_rates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    period_end = Column(DateTime, nullable=False, unique=True)
    import_price = Column(Float, nullable=False)
    export_price = Column(Float, nullable=False)
