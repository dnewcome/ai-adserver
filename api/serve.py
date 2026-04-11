from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from auction.engine import NoFillError, run_auction
from models.base import get_db

router = APIRouter(tags=["serve"])

_JS_PATH = "static/serve.js"


@router.get("/serve/serve.js")
async def serve_js():
    """Serve the publisher tag script."""
    return FileResponse(_JS_PATH, media_type="application/javascript")


@router.get("/serve/{zone_id}")
async def serve_ad(
    zone_id: str,
    request: Request,
    url: str | None = None,          # page URL passed by serve.js
    db: AsyncSession = Depends(get_db),
):
    """
    Called by serve.js on every page load.
    Triggers an auction and returns the winning creative as JSON,
    or 204 on no-fill.
    """
    user_agent = request.headers.get("user-agent")
    try:
        result = await run_auction(
            zone_id=zone_id,
            page_url=url,
            user_agent=user_agent,
            db=db,
        )
    except NoFillError:
        return JSONResponse(status_code=status.HTTP_204_NO_CONTENT, content=None)

    click_url = str(request.base_url) + f"auction/click/{result.impression_id}"

    return {
        "impression_id": result.impression_id,
        "brand_name": result.brand_name,
        "creative": result.creative,
        "click_url": click_url,
        "destination_url": result.destination_url,
    }
