import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base


class Impression(Base):
    __tablename__ = "impressions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    zone_id: Mapped[str] = mapped_column(String, ForeignKey("inventory_zones.id"), nullable=False)
    campaign_id: Mapped[str] = mapped_column(String, ForeignKey("campaigns.id"), nullable=False)

    cpm_paid: Mapped[float] = mapped_column(Float, nullable=False)
    page_url: Mapped[str | None] = mapped_column(Text)
    user_agent: Mapped[str | None] = mapped_column(String(512))

    clicked: Mapped[bool] = mapped_column(default=False)
    clicked_at: Mapped[datetime | None] = mapped_column(DateTime)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    zone: Mapped["InventoryZone"] = relationship("InventoryZone")
    campaign: Mapped["Campaign"] = relationship("Campaign")
