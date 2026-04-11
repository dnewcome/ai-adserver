"""
AI image generation for ad creatives.

Uses DALL-E 3 to generate images from the visual_concept field of each
creative variant. Downloads and stores images locally under static/images/.

DALL-E 3 supported sizes:
  1024x1024  — square (social, native)
  1792x1024  — landscape (leaderboard, OG banner)
  1024x1792  — portrait (skyscraper, mobile interstitial)

Since DALL-E 3 only supports those three sizes we generate a landscape master
and let the browser/CDN handle resizing for other formats.
"""
import logging
import os
from pathlib import Path

import httpx
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from config import settings

logger = logging.getLogger(__name__)

IMAGES_DIR = Path("static/images")

# Map zone_type → DALL-E size
SIZE_MAP = {
    "banner":        "1792x1024",
    "native":        "1024x1024",
    "interstitial":  "1024x1792",
    "video":         "1792x1024",
}
DEFAULT_SIZE = "1792x1024"

IMAGE_PROMPT_TEMPLATE = (
    "Create a high-quality digital advertisement image for {brand_name}. "
    "Visual concept: {visual_concept}. "
    "Style: clean, modern, professional, suitable for online advertising. "
    "No text overlays. Brand feel: {tone}."
)


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=8))
async def _generate_one(prompt: str, size: str, campaign_id: str, variant_id: str) -> str:
    """
    Call DALL-E 3, download the result, save to disk.
    Returns the local relative URL path (e.g. /static/images/<id>/A.png).
    Raises if OPENAI_API_KEY is not set.
    """
    client = AsyncOpenAI(api_key=settings.openai_api_key)

    response = await client.images.generate(
        model="dall-e-3",
        prompt=prompt,
        size=size,
        quality="standard",
        n=1,
    )
    image_url = response.data[0].url

    # Download and persist
    out_dir = IMAGES_DIR / campaign_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{variant_id}.png"

    async with httpx.AsyncClient() as http:
        img_resp = await http.get(image_url, timeout=30)
        img_resp.raise_for_status()
        out_path.write_bytes(img_resp.content)

    local_url = f"/static/images/{campaign_id}/{variant_id}.png"
    logger.info("Image saved: %s", local_url)
    return local_url


async def generate_images_for_campaign(
    campaign_id: str,
    brand_name: str | None,
    tone: str | None,
    creatives: list[dict],
    zone_type: str = "banner",
) -> list[dict]:
    """
    Generate one image per creative variant and attach it as `image_url`.
    Returns the updated creatives list.

    If OPENAI_API_KEY is absent the creatives are returned unchanged.
    Falls back gracefully per-variant — a failure on one won't block others.
    """
    if not settings.openai_api_key:
        logger.warning("OPENAI_API_KEY not set — skipping image generation")
        return creatives

    size = SIZE_MAP.get(zone_type, DEFAULT_SIZE)
    updated = []

    for creative in creatives:
        variant_id = creative.get("variant_id", "A")
        visual_concept = creative.get("visual_concept", "")

        prompt = IMAGE_PROMPT_TEMPLATE.format(
            brand_name=brand_name or "the brand",
            visual_concept=visual_concept,
            tone=tone or "professional and modern",
        )

        try:
            image_url = await _generate_one(prompt, size, campaign_id, variant_id)
            updated.append({**creative, "image_url": image_url})
        except Exception as exc:
            logger.error(
                "Image gen failed for campaign=%s variant=%s: %s",
                campaign_id, variant_id, exc,
            )
            updated.append(creative)  # keep creative without image

    return updated
