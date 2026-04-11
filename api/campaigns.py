from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, HttpUrl

from ai.campaign_creator import create_campaign_from_url

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


class CreateCampaignRequest(BaseModel):
    product_url: HttpUrl
    daily_budget_usd: float | None = None
    total_budget_usd: float | None = None


class CampaignResponse(BaseModel):
    product_url: str
    brand_name: str | None
    brand_description: str | None
    value_propositions: list[str]
    target_audience: dict
    tone_of_voice: str | None
    suggested_categories: list[str]
    bid_floor_cpm: float | None
    ad_creatives: list[dict]
    source_page: dict


@router.post("/create", response_model=CampaignResponse, status_code=status.HTTP_201_CREATED)
async def create_campaign(req: CreateCampaignRequest):
    """
    Submit a product URL and get back a fully-generated ad campaign with creatives.
    """
    try:
        result = await create_campaign_from_url(str(req.product_url))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Campaign creation failed: {exc}",
        )
    return result
