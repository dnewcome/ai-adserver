from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, HttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_publisher
from models.base import get_db
from models.publisher import InventoryZone, Publisher

router = APIRouter(prefix="/publishers", tags=["publishers"])


class AnalyzeSiteRequest(BaseModel):
    site_url: HttpUrl


class InstagramAnalysisRequest(BaseModel):
    handle: str
    followers: int
    engagement_rate: float
    niche: str
    themes: list[str]
    bio: str


class JobAccepted(BaseModel):
    job_id: str
    status: str = "queued"
    poll_url: str


class ZoneResponse(BaseModel):
    id: str
    name: str
    zone_type: str
    dimensions: str | None
    recommended_cpm_usd: float | None
    placement_rationale: str | None
    categories: list | None
    serve_tag: str | None


@router.post("/analyze-site", response_model=JobAccepted, status_code=status.HTTP_202_ACCEPTED)
async def analyze_site(
    req: AnalyzeSiteRequest,
    request: Request,
    publisher: Publisher = Depends(get_current_publisher),
):
    """
    Enqueue site analysis. Returns a job_id immediately.
    Poll GET /jobs/{job_id} for status; result contains zone_ids when done.
    """
    from workers.tasks import analyze_site_task

    base_url = str(request.base_url).rstrip("/")
    task = analyze_site_task.delay(
        publisher_id=publisher.id,
        site_url=str(req.site_url),
        base_url=base_url,
    )
    return JobAccepted(
        job_id=task.id,
        poll_url=f"/jobs/{task.id}",
    )


@router.get("/zones", response_model=list[ZoneResponse])
async def list_zones(
    publisher: Publisher = Depends(get_current_publisher),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(InventoryZone).where(InventoryZone.publisher_id == publisher.id)
    )
    return result.scalars().all()


@router.get("/zones/{zone_id}/tag")
async def get_zone_tag(
    zone_id: str,
    publisher: Publisher = Depends(get_current_publisher),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(InventoryZone).where(
            InventoryZone.id == zone_id,
            InventoryZone.publisher_id == publisher.id,
        )
    )
    zone = result.scalar_one_or_none()
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")
    return {"zone_id": zone_id, "name": zone.name, "serve_tag": zone.serve_tag}


@router.post("/instagram/monetize", status_code=status.HTTP_200_OK)
async def instagram_monetize(
    req: InstagramAnalysisRequest,
    publisher: Publisher = Depends(get_current_publisher),
):
    from ai.publisher_analyzer import analyze_instagram

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
