import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base


class Conversion(Base):
    __tablename__ = "conversions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    impression_id: Mapped[str] = mapped_column(String, ForeignKey("impressions.id"), nullable=False)

    event_type: Mapped[str] = mapped_column(String(64), nullable=False, default="conversion")
    event_data: Mapped[dict | None] = mapped_column(JSON)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    impression: Mapped["Impression"] = relationship("Impression")
