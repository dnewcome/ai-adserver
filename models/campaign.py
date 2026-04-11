import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base


class CampaignStatus(str, PyEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    advertiser_id: Mapped[str] = mapped_column(String, ForeignKey("advertisers.id"), nullable=False)

    # Source
    product_url: Mapped[str] = mapped_column(Text, nullable=False)

    # AI-extracted brand intelligence
    brand_name: Mapped[str | None] = mapped_column(String(255))
    brand_description: Mapped[str | None] = mapped_column(Text)
    value_propositions: Mapped[list | None] = mapped_column(JSON)  # list[str]
    target_audience: Mapped[dict | None] = mapped_column(JSON)     # {demographics, interests, pain_points}
    tone_of_voice: Mapped[str | None] = mapped_column(Text)

    # Generated creatives
    ad_creatives: Mapped[list | None] = mapped_column(JSON)  # list[AdCreative]

    # Targeting & bidding
    suggested_categories: Mapped[list | None] = mapped_column(JSON)  # list[str]
    bid_floor_cpm: Mapped[float | None] = mapped_column(Float)       # suggested minimum CPM in USD
    daily_budget_usd: Mapped[float | None] = mapped_column(Float)
    total_budget_usd: Mapped[float | None] = mapped_column(Float)

    # Marketplace
    status: Mapped[CampaignStatus] = mapped_column(
        SAEnum(CampaignStatus), default=CampaignStatus.PENDING
    )
    is_listed: Mapped[bool] = mapped_column(default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    advertiser: Mapped["Advertiser"] = relationship("Advertiser", back_populates="campaigns")
