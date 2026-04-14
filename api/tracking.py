"""
Conversion tracking endpoints (#16).

  GET  /track/pixel/{impression_id}.gif   — 1×1 transparent GIF pixel
  POST /track/convert/{impression_id}     — server-side postback
"""
import base64

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.base import get_db
from models.conversion import Conversion
from models.impression import Impression

router = APIRouter(prefix="/track", tags=["tracking"])

# Minimal 1×1 transparent GIF (43 bytes)
_PIXEL_GIF = base64.b64decode(
    "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
)


async def _record_conversion(
    impression_id: str,
    event_type: str,
    event_data: dict | None,
    db: AsyncSession,
) -> Conversion:
    result = await db.execute(
        select(Impression).where(Impression.id == impression_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Impression not found")

    conversion = Conversion(
        impression_id=impression_id,
        event_type=event_type,
        event_data=event_data,
    )
    db.add(conversion)
    await db.commit()
    await db.refresh(conversion)
    return conversion


@router.get("/pixel/{impression_id}.gif", include_in_schema=False)
async def conversion_pixel(
    impression_id: str,
    event: str = "conversion",
    db: AsyncSession = Depends(get_db),
):
    """
    Drop a 1×1 GIF on the advertiser's confirmation page to fire a conversion
    automatically when the page loads in the user's browser.

    Usage: <img src="/track/pixel/{impression_id}.gif?event=signup" style="display:none">
    """
    try:
        await _record_conversion(impression_id, event, None, db)  # type: ignore[arg-type]
    except HTTPException:
        pass  # return pixel even if impression not found — avoid exposing errors client-side

    return Response(
        content=_PIXEL_GIF,
        media_type="image/gif",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
        },
    )


class PostbackRequest(BaseModel):
    event_type: str = "conversion"
    event_data: dict | None = None


@router.post("/convert/{impression_id}", status_code=201)
async def postback(
    impression_id: str,
    req: PostbackRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Server-side postback. Advertiser calls this from their backend after a
    conversion (signup, purchase, etc.) to link it back to the impression.
    """
    conversion = await _record_conversion(
        impression_id, req.event_type, req.event_data, db
    )
    return {"conversion_id": conversion.id, "impression_id": impression_id, "event_type": conversion.event_type}
