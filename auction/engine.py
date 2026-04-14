"""
Second-price auction engine.

Flow:
  1. Receive a bid request (zone_id, page_url, user_agent, visitor_id)
  2. Load zone categories from DB
  3. Fetch eligible campaigns from Redis cache (fallback to DB)
  4. Filter: active, listed, advertiser has sufficient balance
  5. Apply frequency cap (per visitor per campaign, Redis counter)
  6. Apply budget pacing (daily spend rate, Redis counter)
  7. Sort by bid_floor_cpm descending
  8. Winner pays max(second_price, floor) + $0.01
  9. Deduct cost from advertiser balance
 10. Record Impression row
 11. Return winning creative payload
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from auction.cache import (
    get_campaigns_for_categories,
    get_freq_count,
    get_today_spend,
    increment_freq,
    increment_today_spend,
    refresh_campaign_index,
)
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
            "frequency_cap": campaign.frequency_cap,
        })
    return campaigns


async def run_auction(
    zone_id: str,
    page_url: str | None,
    user_agent: str | None,
    db: AsyncSession,
    visitor_id: str | None = None,
) -> AuctionResult:
    # 1. Load zone
    zone_result = await db.execute(
        select(InventoryZone).where(InventoryZone.id == zone_id)
    )
    zone = zone_result.scalar_one_or_none()
    if not zone:
        raise NoFillError(f"Zone {zone_id} not found")

    zone_cats = set(zone.categories or [])
    run_of_network = not zone_cats  # #17: zones with no categories match all campaigns

    # 2. Try Redis cache; fall back to DB and repopulate cache
    candidates = await get_campaigns_for_categories(list(zone_cats)) if zone_cats else []
    if not candidates:
        all_campaigns = await _load_active_campaigns(db)
        await refresh_campaign_index(all_campaigns)
        candidates = [
            c for c in all_campaigns
            if run_of_network or (zone_cats & set(c.get("suggested_categories") or []))
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

    # 4. Frequency capping — exclude campaigns the visitor has seen too many times today
    if visitor_id:
        uncapped = []
        for c in eligible:
            cap = c.get("frequency_cap")
            if cap is None:
                uncapped.append(c)
                continue
            count = await get_freq_count(visitor_id, c["id"])
            if count < cap:
                uncapped.append(c)
        if uncapped:
            eligible = uncapped
        # If every campaign is capped for this visitor, serve anyway (best-effort)

    # 5. Budget pacing — skip campaigns spending too fast relative to daily budget
    now_utc = datetime.now(timezone.utc)
    hours_elapsed = now_utc.hour + now_utc.minute / 60
    paced = []
    for c in eligible:
        daily_budget = c.get("daily_budget_usd")
        if not daily_budget:
            paced.append(c)
            continue
        target_so_far = daily_budget * (hours_elapsed / 24)
        today_spend = await get_today_spend(c["id"])
        if today_spend <= target_so_far * 1.2:
            paced.append(c)
    if paced:
        eligible = paced
    # If all campaigns are overpacing, serve anyway (avoid needless no-fill)

    # 6. Second-price auction
    eligible.sort(key=lambda c: c["bid_floor_cpm"], reverse=True)
    winner = eligible[0]
    second_price = eligible[1]["bid_floor_cpm"] if len(eligible) > 1 else winner["bid_floor_cpm"]
    cpm_paid = round(second_price + 0.01, 4)

    # 7. Deduct from advertiser balance
    cpe = cost_per_impression(cpm_paid)
    await db.execute(
        update(Advertiser)
        .where(Advertiser.id == winner["advertiser_id"])
        .values(balance_usd=Advertiser.balance_usd - cpe)
    )

    # 8. Pick best creative (first variant; future: pick by format match)
    creative = winner["ad_creatives"][0]

    # 9. Record impression
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

    # 10. Post-win: update frequency and pacing counters
    if visitor_id:
        await increment_freq(visitor_id, winner["id"])
    await increment_today_spend(winner["id"], cpe)

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
