import uuid
from sqlalchemy import Column, DateTime, Float, ForeignKey, String, JSON
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.core.database import Base

class Schedule(Base):
    __tablename__ = "schedules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    optimisation_run_id = Column(UUID(as_uuid=True), ForeignKey("optimisation_runs.id"))

    status = Column(String, default="draft")
    sent_at = Column(DateTime)
    provider_response = Column(JSON)

    pushed_at = Column(DateTime(timezone=True))
    foxess_groups = Column(JSONB)
    trigger_source = Column(String)  # 'cron' | 'manual'
    soc_at_push = Column(Float)
    error_message = Column(String)