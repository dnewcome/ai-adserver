from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, HttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai.publisher_analyzer import analyze_instagram, analyze_publisher_site, _generate_serve_tag
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


class ZoneResponse(BaseModel):
    id: str
    name: str
    zone_type: str
    dimensions: str | None
    recommended_cpm_usd: float | None
    placement_rationale: str | None
    categories: list | None
    serve_tag: str | None


@router.post("/analyze-site", status_code=status.HTTP_200_OK)
async def analyze_site(
    req: AnalyzeSiteRequest,
    request: Request,
    publisher: Publisher = Depends(get_current_publisher),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await analyze_publisher_site(str(req.site_url))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Site analysis failed: {exc}",
        )

    base_url = str(request.base_url).rstrip("/")

    saved_zones = []
    for zone in result.get("recommended_zones", []):
        iz = InventoryZone(
            publisher_id=publisher.id,
            name=zone["name"],
            zone_type=zone["zone_type"],
            dimensions=zone.get("dimensions"),
            recommended_cpm_usd=zone.get("recommended_cpm_usd"),
            placement_rationale=zone.get("placement_rationale"),
            categories=zone.get("categories", []),
        )
        db.add(iz)
        saved_zones.append(iz)

    await db.commit()
    for z in saved_zones:
        await db.refresh(z)
        # Generate serve tag now that we have a stable zone UUID
        z.serve_tag = _generate_serve_tag(z.id, z.zone_type, base_url)

    await db.commit()

    zones_out = [
        {
            "id": z.id,
            "name": z.name,
            "zone_type": z.zone_type,
            "dimensions": z.dimensions,
            "recommended_cpm_usd": z.recommended_cpm_usd,
            "placement_rationale": z.placement_rationale,
            "categories": z.categories,
            "serve_tag": z.serve_tag,
        }
        for z in saved_zones
    ]
    return {**result, "recommended_zones": zones_out}


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
