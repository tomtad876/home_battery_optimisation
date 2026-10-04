import uuid
from sqlalchemy import Boolean, Column, DateTime, String, text
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base

class Site(Base):
    __tablename__ = "sites"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    timezone = Column(String, nullable=False)
    user_id = Column(String, nullable=True, index=True)
    # While the household is away the demand forecast collapses to baseload
    # (plus explicitly scheduled events) instead of the 7-day average.
    holiday_mode = Column(Boolean, nullable=False, server_default=text("false"))
    # Optional auto-expiry: after this instant holiday mode is treated as off.
    holiday_until = Column(DateTime(timezone=True), nullable=True)