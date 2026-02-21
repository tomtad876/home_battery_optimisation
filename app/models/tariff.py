from sqlalchemy import Column, String, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base

class Tariff(Base):
    __tablename__ = "tariffs"

    id = Column(UUID(as_uuid=True), primary_key=True)
    site_id = Column(UUID(as_uuid=True), ForeignKey("sites.id"))

    import_type = Column(String, nullable=False)
    export_type = Column(String, nullable=False)

    config_json = Column(JSON, nullable=True)