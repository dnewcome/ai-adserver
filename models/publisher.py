import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base


class Publisher(Base):
    __tablename__ = "publishers"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    site_url: Mapped[str | None] = mapped_column(Text)
    instagram_handle: Mapped[str | None] = mapped_column(String(255))

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    inventory_zones: Mapped[list["InventoryZone"]] = relationship("InventoryZone", back_populates="publisher")


class InventoryZone(Base):
    """A named placement slot on a publisher's site (e.g. 'above-fold-banner')."""
    __tablename__ = "inventory_zones"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    publisher_id: Mapped[str] = mapped_column(String, ForeignKey("publishers.id"), nullable=False)

    name: Mapped[str] = mapped_column(String(255), nullable=False)      # e.g. "above-fold-banner"
    zone_type: Mapped[str] = mapped_column(String(50), nullable=False)  # banner | interstitial | native | video
    dimensions: Mapped[str | None] = mapped_column(String(50))          # e.g. "728x90"

    # AI recommendations
    recommended_cpm_usd: Mapped[float | None] = mapped_column(Float)
    placement_rationale: Mapped[str | None] = mapped_column(Text)
    categories: Mapped[list | None] = mapped_column(JSON)               # content categories for matching

    # Serve tag (JS snippet)
    serve_tag: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    publisher: Mapped["Publisher"] = relationship("Publisher", back_populates="inventory_zones")
