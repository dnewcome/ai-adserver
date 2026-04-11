from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auction.engine import NoFillError, run_auction
from models.base import get_db
from models.campaign import Campaign
from models.impression import Impression

router = APIRouter(prefix="/auction", tags=["auction"])


class BidRequest(BaseModel):
    zone_id: str
    page_url: str | None = None


class BidResponse(BaseModel):
    impression_id: str
    campaign_id: str
    brand_name: str | None
    creative: dict
    cpm_paid: float
    destination_url: str
    click_url: str


@router.post("/bid", response_model=BidResponse)
async def bid(
    req: BidRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Called by the serve.js tag on every ad slot load.
    Returns the winning creative or 204 No Content on no-fill.
    """
    user_agent = request.headers.get("user-agent")
    try:
        result = await run_auction(
            zone_id=req.zone_id,
            page_url=req.page_url,
            user_agent=user_agent,
            db=db,
        )
    except NoFillError as exc:
        raise HTTPException(status_code=status.HTTP_204_NO_CONTENT, detail=str(exc))

    click_url = str(request.base_url) + f"auction/click/{result.impression_id}"

    return BidResponse(
        impression_id=result.impression_id,
        campaign_id=result.campaign_id,
        brand_name=result.brand_name,
        creative=result.creative,
        cpm_paid=result.cpm_paid,
        destination_url=result.destination_url,
        click_url=click_url,
    )


@router.get("/click/{impression_id}", status_code=status.HTTP_302_FOUND)
async def click(
    impression_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Record a click and redirect to the advertiser's destination URL."""
    imp_result = await db.execute(
        select(Impression).where(Impression.id == impression_id)
    )
    impression = imp_result.scalar_one_or_none()
    if not impression:
        raise HTTPException(status_code=404, detail="Impression not found")

    if not impression.clicked:
        impression.clicked = True
        impression.clicked_at = datetime.utcnow()
        await db.commit()

    camp_result = await db.execute(
        select(Campaign).where(Campaign.id == impression.campaign_id)
    )
    campaign = camp_result.scalar_one_or_none()
    destination = campaign.product_url if campaign else "/"
    return RedirectResponse(url=destination)
