"""
Second-price auction engine.

Flow:
  1. Receive a bid request (zone_id, page_url, user_agent)
  2. Load zone categories from DB
  3. Fetch eligible campaigns from Redis cache (fallback to DB)
  4. Filter: active, listed, advertiser has sufficient balance
  5. Sort by bid_floor_cpm descending
  6. Winner pays max(second_price, floor) + $0.01
  7. Deduct cost from advertiser balance
  8. Record Impression row
  9. Return winning creative payload
"""
import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from auction.cache import get_campaigns_for_categories, refresh_campaign_index
from models.advertiser import Advertiser
from models.campaign import Campaign, CampaignStatus
from models.impression import Impression
from models.publisher import InventoryZone

logger = logging.getLogger(__name__)

# Minimum CPM floor if a campaign has none set
DEFAULT_FLOOR_CPM = 0.50
# Cost per impression = CPM / 1000
CPM_TO_CPE = 1 / 1000


@dataclass
class AuctionResult:
    impression_id: str
    campaign_id: str
    brand_name: str | None
    creative: dict           # the winning ad_creative variant
    cpm_paid: float
    destination_url: str


class NoFillError(Exception):
    """Raised when no eligible campaigns are available for a zone."""


async def _load_active_campaigns(db: AsyncSession) -> list[dict]:
    """Query DB for all active+listed campaigns and return as dicts."""
    result = await db.execute(
        select(Campaign, Advertiser)
        .join(Advertiser, Campaign.advertiser_id == Advertiser.id)
        .where(
            Campaign.status == CampaignStatus.ACTIVE,
            Campaign.is_listed == True,  # noqa: E712
        )
    )
    rows = result.all()
    campaigns = []
    for campaign, advertiser in rows:
        campaigns.append({
            "id": campaign.id,
            "advertiser_id": campaign.advertiser_id,
            "advertiser_balance": advertiser.balance_usd,
            "product_url": campaign.product_url,
            "brand_name": campaign.brand_name,
            "bid_floor_cpm": campaign.bid_floor_cpm or DEFAULT_FLOOR_CPM,
            "suggested_categories": campaign.suggested_categories or [],
            "ad_creatives": campaign.ad_creatives or [],
            "daily_budget_usd": campaign.daily_budget_usd,
            "total_budget_usd": campaign.total_budget_usd,
        })
    return campaigns


async def run_auction(
    zone_id: str,
    page_url: str | None,
    user_agent: str | None,
    db: AsyncSession,
) -> AuctionResult:
    # 1. Load zone
    zone_result = await db.execute(
        select(InventoryZone).where(InventoryZone.id == zone_id)
    )
    zone = zone_result.scalar_one_or_none()
    if not zone:
        raise NoFillError(f"Zone {zone_id} not found")

    zone_cats = set(zone.categories or [])

    # 2. Try Redis cache; fall back to DB and repopulate cache
    candidates = await get_campaigns_for_categories(list(zone_cats))
    if not candidates:
        all_campaigns = await _load_active_campaigns(db)
        await refresh_campaign_index(all_campaigns)
        candidates = [
            c for c in all_campaigns
            if zone_cats & set(c.get("suggested_categories") or [])
        ]

    if not candidates:
        raise NoFillError("No campaigns match zone categories")

    # 3. Filter: must have enough balance to pay for at least one impression
    cost_per_impression = lambda cpm: cpm * CPM_TO_CPE  # noqa: E731
    eligible = [
        c for c in candidates
        if c["advertiser_balance"] >= cost_per_impression(c["bid_floor_cpm"])
        and c["ad_creatives"]
    ]

    if not eligible:
        raise NoFillError("No campaigns with sufficient balance")

    # 4. Second-price auction
    eligible.sort(key=lambda c: c["bid_floor_cpm"], reverse=True)
    winner = eligible[0]
    second_price = eligible[1]["bid_floor_cpm"] if len(eligible) > 1 else winner["bid_floor_cpm"]
    cpm_paid = round(second_price + 0.01, 4)

    # 5. Deduct from advertiser balance
    cpe = cost_per_impression(cpm_paid)
    await db.execute(
        update(Advertiser)
        .where(Advertiser.id == winner["advertiser_id"])
        .values(balance_usd=Advertiser.balance_usd - cpe)
    )

    # 6. Pick best creative (first variant; future: pick by format match)
    creative = winner["ad_creatives"][0]

    # 7. Record impression
    impression = Impression(
        zone_id=zone_id,
        campaign_id=winner["id"],
        cpm_paid=cpm_paid,
        page_url=page_url,
        user_agent=user_agent,
        created_at=datetime.utcnow(),
    )
    db.add(impression)
    await db.commit()
    await db.refresh(impression)

    logger.info(
        "Auction won: campaign=%s zone=%s cpm=%.4f impression=%s",
        winner["id"], zone_id, cpm_paid, impression.id,
    )

    return AuctionResult(
        impression_id=impression.id,
        campaign_id=winner["id"],
        brand_name=winner["brand_name"],
        creative=creative,
        cpm_paid=cpm_paid,
        destination_url=winner["product_url"],
    )
