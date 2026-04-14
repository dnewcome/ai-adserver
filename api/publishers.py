from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, HttpUrl
from sqlalchemy import Integer, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_publisher
from models.base import get_db
from models.impression import Impression
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


@router.get("/zones/{zone_id}/stats", tags=["analytics"])
async def get_zone_stats(
    zone_id: str,
    from_date: date = Query(default=None, description="Start date (YYYY-MM-DD), defaults to 30 days ago"),
    to_date: date = Query(default=None, description="End date (YYYY-MM-DD), defaults to today"),
    publisher: Publisher = Depends(get_current_publisher),
    db: AsyncSession = Depends(get_db),
):
    """Impressions, revenue, and fill rate aggregated by day for a zone."""
    zone_result = await db.execute(
        select(InventoryZone).where(
            InventoryZone.id == zone_id,
            InventoryZone.publisher_id == publisher.id,
        )
    )
    if not zone_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Zone not found")

    from_dt = datetime.combine(from_date or date.fromordinal(date.today().toordinal() - 30), datetime.min.time())
    to_dt = datetime.combine(to_date or date.today(), datetime.max.time())

    rows = await db.execute(
        select(
            func.date(Impression.created_at).label("day"),
            func.count(Impression.id).label("impressions"),
            func.sum(cast(Impression.clicked, Integer)).label("clicks"),
            func.sum(Impression.cpm_paid / 1000).label("revenue_usd"),
        )
        .where(
            Impression.zone_id == zone_id,
            Impression.created_at >= from_dt,
            Impression.created_at <= to_dt,
        )
        .group_by(func.date(Impression.created_at))
        .order_by(func.date(Impression.created_at))
    )
    daily = []
    total_impressions = total_clicks = total_revenue = 0
    for row in rows:
        imps = row.impressions or 0
        clicks = int(row.clicks or 0)
        rev = float(row.revenue_usd or 0)
        total_impressions += imps
        total_clicks += clicks
        total_revenue += rev
        daily.append({
            "day": str(row.day),
            "impressions": imps,
            "clicks": clicks,
            "ctr_pct": round(100 * clicks / imps, 2) if imps else 0,
            "revenue_usd": round(rev, 4),
        })

    return {
        "zone_id": zone_id,
        "from_date": str(from_dt.date()),
        "to_date": str(to_dt.date()),
        "totals": {
            "impressions": total_impressions,
            "clicks": total_clicks,
            "ctr_pct": round(100 * total_clicks / total_impressions, 2) if total_impressions else 0,
            "revenue_usd": round(total_revenue, 4),
        },
        "daily": daily,
    }


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
