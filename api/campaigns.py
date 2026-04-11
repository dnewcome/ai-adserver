from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, HttpUrl, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_advertiser
from models.advertiser import Advertiser
from models.base import get_db
from models.campaign import Campaign

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
