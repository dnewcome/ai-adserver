import os

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from auction.engine import NoFillError, run_auction
from models.base import get_db

router = APIRouter(tags=["serve"])

_JS_PATH = "static/serve.js"

# ---------------------------------------------------------------------------
# Bot filtering (#15) — loaded once at startup from a plain-text blocklist.
# Each line is a lowercase substring matched against the incoming User-Agent.
# ---------------------------------------------------------------------------
_BOT_UA_FILE = "data/bot_useragents.txt"
_BOT_STRINGS: list[str] = []
if os.path.exists(_BOT_UA_FILE):
    with open(_BOT_UA_FILE) as _f:
        _BOT_STRINGS = [
            line.strip().lower()
            for line in _f
            if line.strip() and not line.startswith("#")
        ]


def _is_bot(user_agent: str | None) -> bool:
    if not user_agent or not _BOT_STRINGS:
        return False
    ua_lower = user_agent.lower()
    return any(s in ua_lower for s in _BOT_STRINGS)


@router.get("/serve/serve.js")
async def serve_js():
    """Serve the publisher tag script."""
    return FileResponse(_JS_PATH, media_type="application/javascript")


@router.get("/serve/{zone_id}")
async def serve_ad(
    zone_id: str,
    request: Request,
    url: str | None = None,          # page URL passed by serve.js
    visitor_id: str | None = None,   # first-party visitor cookie set by serve.js
    db: AsyncSession = Depends(get_db),
):
    """
    Called by serve.js on every page load.
    Triggers an auction and returns the winning creative as JSON,
    or 204 on no-fill.
    """
    user_agent = request.headers.get("user-agent")

    if _is_bot(user_agent):
        return JSONResponse(status_code=status.HTTP_204_NO_CONTENT, content=None)

    try:
        result = await run_auction(
            zone_id=zone_id,
            page_url=url,
            user_agent=user_agent,
            db=db,
            visitor_id=visitor_id,
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
