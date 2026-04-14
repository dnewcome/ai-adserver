from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, HttpUrl, field_validator
from sqlalchemy import Integer, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_advertiser
from models.advertiser import Advertiser
from models.base import get_db
from models.campaign import Campaign
from models.impression import Impression

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


class CreateCampaignRequest(BaseModel):
    product_url: HttpUrl
    daily_budget_usd: float | None = None
    total_budget_usd: float | None = None
    frequency_cap: int | None = None


class CampaignResponse(BaseModel):
    id: str
    product_url: str
    brand_name: str | None = None
    brand_description: str | None = None
    value_propositions: list = []
    target_audience: dict = {}
    tone_of_voice: str | None = None
    suggested_categories: list = []
    bid_floor_cpm: float | None = None
    daily_budget_usd: float | None = None
    total_budget_usd: float | None = None
    frequency_cap: int | None = None
    ad_creatives: list = []
    status: str
    images_status: str | None = None

    model_config = {"from_attributes": True}

    @field_validator("value_propositions", "suggested_categories", "ad_creatives", mode="before")
    @classmethod
    def none_to_list(cls, v):
        return v if v is not None else []

    @field_validator("target_audience", mode="before")
    @classmethod
    def none_to_dict(cls, v):
        return v if v is not None else {}


class JobAccepted(BaseModel):
    job_id: str
    status: str = "queued"
    poll_url: str


@router.post("/create", response_model=JobAccepted, status_code=status.HTTP_202_ACCEPTED)
async def create_campaign(
    req: CreateCampaignRequest,
    advertiser: Advertiser = Depends(get_current_advertiser),
):
    """
    Enqueue campaign creation. Returns a job_id immediately.
    Poll GET /jobs/{job_id} for status; result contains campaign_id when done.
    """
    from workers.tasks import create_campaign_task

    task = create_campaign_task.delay(
        advertiser_id=advertiser.id,
        product_url=str(req.product_url),
        daily_budget_usd=req.daily_budget_usd,
        total_budget_usd=req.total_budget_usd,
        frequency_cap=req.frequency_cap,
    )
    return JobAccepted(
        job_id=task.id,
        poll_url=f"/jobs/{task.id}",
    )


@router.get("", response_model=list[CampaignResponse])
async def list_campaigns(
    advertiser: Advertiser = Depends(get_current_advertiser),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Campaign).where(Campaign.advertiser_id == advertiser.id)
    )
    return result.scalars().all()


@router.get("/{campaign_id}", response_model=CampaignResponse)
async def get_campaign(
    campaign_id: str,
    advertiser: Advertiser = Depends(get_current_advertiser),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Campaign).where(
            Campaign.id == campaign_id,
            Campaign.advertiser_id == advertiser.id,
        )
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


@router.get("/{campaign_id}/stats", tags=["analytics"])
async def get_campaign_stats(
    campaign_id: str,
    from_date: date = Query(default=None, description="Start date (YYYY-MM-DD), defaults to 30 days ago"),
    to_date: date = Query(default=None, description="End date (YYYY-MM-DD), defaults to today"),
    advertiser: Advertiser = Depends(get_current_advertiser),
    db: AsyncSession = Depends(get_db),
):
    """Impressions, clicks, CTR, and spend aggregated by day for a campaign."""
    result = await db.execute(
        select(Campaign).where(
            Campaign.id == campaign_id,
            Campaign.advertiser_id == advertiser.id,
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Campaign not found")

    from_dt = datetime.combine(from_date or date.fromordinal(date.today().toordinal() - 30), datetime.min.time())
    to_dt = datetime.combine(to_date or date.today(), datetime.max.time())

    rows = await db.execute(
        select(
            func.date(Impression.created_at).label("day"),
            func.count(Impression.id).label("impressions"),
            func.sum(cast(Impression.clicked, Integer)).label("clicks"),
            func.sum(Impression.cpm_paid / 1000).label("spend_usd"),
        )
        .where(
            Impression.campaign_id == campaign_id,
            Impression.created_at >= from_dt,
            Impression.created_at <= to_dt,
        )
        .group_by(func.date(Impression.created_at))
        .order_by(func.date(Impression.created_at))
    )
    daily = []
    total_impressions = total_clicks = total_spend = 0
    for row in rows:
        imps = row.impressions or 0
        clicks = int(row.clicks or 0)
        spend = float(row.spend_usd or 0)
        total_impressions += imps
        total_clicks += clicks
        total_spend += spend
        daily.append({
            "day": str(row.day),
            "impressions": imps,
            "clicks": clicks,
            "ctr_pct": round(100 * clicks / imps, 2) if imps else 0,
            "spend_usd": round(spend, 4),
        })

    return {
        "campaign_id": campaign_id,
        "from_date": str(from_dt.date()),
        "to_date": str(to_dt.date()),
        "totals": {
            "impressions": total_impressions,
            "clicks": total_clicks,
            "ctr_pct": round(100 * total_clicks / total_impressions, 2) if total_impressions else 0,
            "spend_usd": round(total_spend, 4),
        },
        "daily": daily,
    }
