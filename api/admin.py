"""
Dev-only admin API — no authentication.
Mounts at /admin/api/...
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import Integer, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.advertiser import Advertiser
from models.base import get_db
from models.campaign import Campaign
from models.impression import Impression
from models.publisher import InventoryZone, Publisher

router = APIRouter(prefix="/admin/api", tags=["admin"])


# ---------------------------------------------------------------------------
# Advertisers
# ---------------------------------------------------------------------------

@router.get("/advertisers")
async def list_advertisers(db: AsyncSession = Depends(get_db)):
    """List all advertisers with their current balance."""
    result = await db.execute(select(Advertiser).order_by(Advertiser.created_at.desc()))
    advertisers = result.scalars().all()
    return [
        {
            "id": a.id,
            "email": a.email,
            "company_name": a.company_name,
            "balance_usd": a.balance_usd,
            "created_at": a.created_at.isoformat(),
        }
        for a in advertisers
    ]


class SetBalanceRequest(BaseModel):
    balance_usd: float


@router.post("/advertisers/{advertiser_id}/balance")
async def set_balance(
    advertiser_id: str,
    req: SetBalanceRequest,
    db: AsyncSession = Depends(get_db),
):
    """Directly set an advertiser's account balance (admin override)."""
    result = await db.execute(select(Advertiser).where(Advertiser.id == advertiser_id))
    advertiser = result.scalar_one_or_none()
    if not advertiser:
        raise HTTPException(status_code=404, detail="Advertiser not found")
    advertiser.balance_usd = req.balance_usd
    await db.commit()
    return {"id": advertiser_id, "balance_usd": advertiser.balance_usd}


# ---------------------------------------------------------------------------
# Campaigns + stats
# ---------------------------------------------------------------------------

@router.get("/campaigns")
async def list_campaigns(db: AsyncSession = Depends(get_db)):
    """List all campaigns across all advertisers with impression/click/spend aggregates."""
    # Campaigns joined with impression aggregates
    imp_q = (
        select(
            Impression.campaign_id,
            func.count(Impression.id).label("impressions"),
            func.sum(cast(Impression.clicked, Integer)).label("clicks"),
            func.sum(Impression.cpm_paid / 1000).label("spend_usd"),
        )
        .group_by(Impression.campaign_id)
        .subquery()
    )

    q = (
        select(Campaign, Advertiser.email, Advertiser.company_name, imp_q)
        .join(Advertiser, Campaign.advertiser_id == Advertiser.id)
        .outerjoin(imp_q, Campaign.id == imp_q.c.campaign_id)
        .order_by(Campaign.created_at.desc())
    )
    rows = (await db.execute(q)).all()

    campaigns = []
    for row in rows:
        c = row.Campaign
        impressions = row.impressions or 0
        clicks = row.clicks or 0
        spend = float(row.spend_usd or 0)
        campaigns.append(
            {
                "id": c.id,
                "brand_name": c.brand_name,
                "product_url": c.product_url,
                "status": c.status.value if c.status else None,
                "images_status": c.images_status,
                "bid_floor_cpm": c.bid_floor_cpm,
                "daily_budget_usd": c.daily_budget_usd,
                "total_budget_usd": c.total_budget_usd,
                "tone_of_voice": c.tone_of_voice,
                "value_propositions": c.value_propositions or [],
                "target_audience": c.target_audience or {},
                "suggested_categories": c.suggested_categories or [],
                "ad_creatives": c.ad_creatives or [],
                "advertiser_email": row.email,
                "advertiser_company": row.company_name,
                "impressions": impressions,
                "clicks": clicks,
                "ctr_pct": round(100 * clicks / impressions, 2) if impressions else 0,
                "spend_usd": round(spend, 4),
                "created_at": c.created_at.isoformat(),
            }
        )
    return campaigns


class CreateCampaignAdminRequest(BaseModel):
    product_url: str
    advertiser_id: str
    daily_budget_usd: float | None = None
    total_budget_usd: float | None = None


@router.post("/campaigns/create")
async def admin_create_campaign(
    req: CreateCampaignAdminRequest,
    db: AsyncSession = Depends(get_db),
):
    """Enqueue AI campaign generation from a product URL on behalf of any advertiser."""
    from workers.tasks import create_campaign_task

    result = await db.execute(select(Advertiser).where(Advertiser.id == req.advertiser_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Advertiser not found")

    task = create_campaign_task.delay(
        advertiser_id=req.advertiser_id,
        product_url=req.product_url,
        daily_budget_usd=req.daily_budget_usd,
        total_budget_usd=req.total_budget_usd,
    )
    return {"job_id": task.id, "status": "queued", "poll_url": f"/jobs/{task.id}"}


class SetCampaignStatusRequest(BaseModel):
    status: str  # ACTIVE | PAUSED


@router.post("/campaigns/{campaign_id}/status")
async def set_campaign_status(
    campaign_id: str,
    req: SetCampaignStatusRequest,
    db: AsyncSession = Depends(get_db),
):
    """Set a campaign's status to ACTIVE or PAUSED."""
    from models.campaign import CampaignStatus

    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    try:
        campaign.status = CampaignStatus[req.status.upper()]
    except KeyError:
        raise HTTPException(status_code=400, detail=f"Invalid status: {req.status}")
    await db.commit()
    return {"id": campaign_id, "status": campaign.status.value}


# ---------------------------------------------------------------------------
# Publishers + zones
# ---------------------------------------------------------------------------

@router.get("/publishers")
async def list_publishers(db: AsyncSession = Depends(get_db)):
    """List all publishers."""
    result = await db.execute(select(Publisher).order_by(Publisher.created_at.desc()))
    publishers = result.scalars().all()
    return [
        {
            "id": p.id,
            "email": p.email,
            "site_url": p.site_url,
            "created_at": p.created_at.isoformat(),
        }
        for p in publishers
    ]


@router.get("/zones")
async def list_zones(db: AsyncSession = Depends(get_db)):
    """List all inventory zones across all publishers with impression/revenue aggregates."""
    # Zone impression stats subquery
    imp_q = (
        select(
            Impression.zone_id,
            func.count(Impression.id).label("impressions"),
            func.sum(Impression.cpm_paid / 1000).label("revenue_usd"),
        )
        .group_by(Impression.zone_id)
        .subquery()
    )

    q = (
        select(InventoryZone, Publisher.email, Publisher.site_url, imp_q)
        .join(Publisher, InventoryZone.publisher_id == Publisher.id)
        .outerjoin(imp_q, InventoryZone.id == imp_q.c.zone_id)
        .order_by(InventoryZone.created_at.desc())
    )
    rows = (await db.execute(q)).all()

    return [
        {
            "id": row.InventoryZone.id,
            "name": row.InventoryZone.name,
            "zone_type": row.InventoryZone.zone_type,
            "dimensions": row.InventoryZone.dimensions,
            "recommended_cpm_usd": row.InventoryZone.recommended_cpm_usd,
            "categories": row.InventoryZone.categories or [],
            "placement_rationale": row.InventoryZone.placement_rationale,
            "serve_tag": row.InventoryZone.serve_tag,
            "publisher_email": row.email,
            "publisher_site": row.site_url,
            "impressions": row.impressions or 0,
            "revenue_usd": round(float(row.revenue_usd or 0), 4),
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Recent impressions
# ---------------------------------------------------------------------------

@router.get("/impressions")
async def list_impressions(limit: int = 50, db: AsyncSession = Depends(get_db)):
    """Return the most recent impressions with brand and zone info (default last 50)."""
    q = (
        select(Impression, Campaign.brand_name, InventoryZone.name.label("zone_name"))
        .join(Campaign, Impression.campaign_id == Campaign.id)
        .join(InventoryZone, Impression.zone_id == InventoryZone.id)
        .order_by(Impression.created_at.desc())
        .limit(limit)
    )
    rows = (await db.execute(q)).all()
    return [
        {
            "id": row.Impression.id,
            "brand_name": row.brand_name,
            "zone_name": row.zone_name,
            "cpm_paid": row.Impression.cpm_paid,
            "clicked": row.Impression.clicked,
            "clicked_at": row.Impression.clicked_at.isoformat() if row.Impression.clicked_at else None,
            "page_url": row.Impression.page_url,
            "created_at": row.Impression.created_at.isoformat(),
        }
        for row in rows
    ]
