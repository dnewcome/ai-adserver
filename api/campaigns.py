from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, HttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai.campaign_creator import create_campaign_from_url
from api.auth import get_current_advertiser
from models.advertiser import Advertiser
from models.base import get_db
from models.campaign import Campaign, CampaignStatus

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


class CreateCampaignRequest(BaseModel):
    product_url: HttpUrl
    daily_budget_usd: float | None = None
    total_budget_usd: float | None = None


class CampaignResponse(BaseModel):
    id: str
    product_url: str
    brand_name: str | None
    brand_description: str | None
    value_propositions: list
    target_audience: dict
    tone_of_voice: str | None
    suggested_categories: list
    bid_floor_cpm: float | None
    ad_creatives: list
    status: str


@router.post("/create", response_model=CampaignResponse, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    req: CreateCampaignRequest,
    advertiser: Advertiser = Depends(get_current_advertiser),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await create_campaign_from_url(str(req.product_url))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Campaign creation failed: {exc}",
        )

    campaign = Campaign(
        advertiser_id=advertiser.id,
        product_url=result["product_url"],
        brand_name=result.get("brand_name"),
        brand_description=result.get("brand_description"),
        value_propositions=result.get("value_propositions", []),
        target_audience=result.get("target_audience", {}),
        tone_of_voice=result.get("tone_of_voice"),
        suggested_categories=result.get("suggested_categories", []),
        bid_floor_cpm=result.get("bid_floor_cpm"),
        ad_creatives=result.get("ad_creatives", []),
        daily_budget_usd=req.daily_budget_usd,
        total_budget_usd=req.total_budget_usd,
        status=CampaignStatus.ACTIVE,
        is_listed=True,
    )
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)
    return campaign


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
