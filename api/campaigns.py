import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, HttpUrl, field_validator
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ai.campaign_creator import create_campaign_from_url
from ai.image_gen import generate_images_for_campaign
from api.auth import get_current_advertiser
from models.advertiser import Advertiser
from models.base import AsyncSessionLocal, get_db
from models.campaign import Campaign, CampaignStatus

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/campaigns", tags=["campaigns"])


class CreateCampaignRequest(BaseModel):
    product_url: HttpUrl
    daily_budget_usd: float | None = None
    total_budget_usd: float | None = None


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


async def _attach_images(campaign_id: str, brand_name: str | None, tone: str | None) -> None:
    """
    Background task: generate images for all creative variants and
    persist them back to the campaign row.
    Uses its own DB session (the request session is closed by this point).
    """
    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
            campaign = result.scalar_one_or_none()
            if not campaign:
                return

            updated_creatives = await generate_images_for_campaign(
                campaign_id=campaign_id,
                brand_name=brand_name,
                tone=tone,
                creatives=campaign.ad_creatives or [],
            )

            await db.execute(
                update(Campaign)
                .where(Campaign.id == campaign_id)
                .values(ad_creatives=updated_creatives, images_status="done")
            )
            await db.commit()
            logger.info("Images attached to campaign %s", campaign_id)
        except Exception as exc:
            logger.error("Image background task failed for %s: %s", campaign_id, exc)
            await db.execute(
                update(Campaign)
                .where(Campaign.id == campaign_id)
                .values(images_status="failed")
            )
            await db.commit()


@router.post("/create", response_model=CampaignResponse, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    req: CreateCampaignRequest,
    background_tasks: BackgroundTasks,
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
        images_status="pending" if result.get("ad_creatives") else None,
    )
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)

    # Kick off image generation in the background — response returns immediately
    if result.get("ad_creatives"):
        background_tasks.add_task(
            _attach_images,
            campaign.id,
            campaign.brand_name,
            campaign.tone_of_voice,
        )

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
