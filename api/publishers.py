from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, HttpUrl

from ai.publisher_analyzer import analyze_instagram, analyze_publisher_site

router = APIRouter(prefix="/publishers", tags=["publishers"])


class AnalyzeSiteRequest(BaseModel):
    site_url: HttpUrl


class InstagramAnalysisRequest(BaseModel):
    handle: str
    followers: int
    engagement_rate: float          # e.g. 3.5 for 3.5%
    niche: str
    themes: list[str]
    bio: str


@router.post("/analyze-site", status_code=status.HTTP_200_OK)
async def analyze_site(req: AnalyzeSiteRequest):
    """
    Submit a website URL and receive AI-recommended ad inventory zones,
    placement rationale, serve tags, and estimated revenue.
    """
    try:
        result = await analyze_publisher_site(str(req.site_url))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Site analysis failed: {exc}",
        )
    return result


@router.post("/instagram/monetize", status_code=status.HTTP_200_OK)
async def instagram_monetize(req: InstagramAnalysisRequest):
    """
    Provide your Instagram account details and receive a complete
    monetization strategy with affiliate programs, pricing, and action steps.
    """
    try:
        result = await analyze_instagram(
            handle=req.handle,
            followers=req.followers,
            engagement_rate=req.engagement_rate,
            niche=req.niche,
            themes=req.themes,
            bio=req.bio,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Instagram analysis failed: {exc}",
        )
    return result
