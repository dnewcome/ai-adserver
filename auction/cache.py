"""
Redis-backed campaign index for sub-millisecond auction lookups.

Structure:
  auction:campaigns          — JSON list of all active+listed campaign dicts
  auction:campaigns_by_cat:{slug}  — JSON list of campaign IDs in that category

TTL: 60 seconds. Any campaign status change should call invalidate().
"""
import json
import logging

import redis.asyncio as aioredis

from config import settings

logger = logging.getLogger(__name__)

CAMPAIGNS_KEY = "auction:campaigns"
CAT_KEY_PREFIX = "auction:campaigns_by_cat:"
TTL = 60  # seconds


def _redis() -> aioredis.Redis:
    return aioredis.from_url(settings.redis_url, decode_responses=True)


async def get_campaigns_for_categories(categories: list[str]) -> list[dict]:
    """Return cached active campaigns matching any of the given category slugs."""
    async with _redis() as r:
        # Collect candidate IDs from category buckets
        candidate_ids: set[str] = set()
        for cat in categories:
            raw = await r.get(f"{CAT_KEY_PREFIX}{cat}")
            if raw:
                candidate_ids.update(json.loads(raw))

        if not candidate_ids:
            return []

        # Fetch full campaign records from the campaigns index
        all_raw = await r.get(CAMPAIGNS_KEY)
        if not all_raw:
            return []

        all_campaigns: list[dict] = json.loads(all_raw)
        return [c for c in all_campaigns if c["id"] in candidate_ids]


async def refresh_campaign_index(campaigns: list[dict]) -> None:
    """
    Rebuild the Redis campaign index from a fresh DB query result.
    Called after any campaign mutation or on cache miss.
    """
    async with _redis() as r:
        pipe = r.pipeline()
        pipe.set(CAMPAIGNS_KEY, json.dumps(campaigns), ex=TTL)

        # Build per-category buckets
        cat_buckets: dict[str, list[str]] = {}
        for c in campaigns:
            for cat in c.get("suggested_categories") or []:
                cat_buckets.setdefault(cat, []).append(c["id"])

        for cat, ids in cat_buckets.items():
            pipe.set(f"{CAT_KEY_PREFIX}{cat}", json.dumps(ids), ex=TTL)

        await pipe.execute()
    logger.debug("Campaign index refreshed: %d campaigns", len(campaigns))


async def invalidate() -> None:
    """Flush the entire auction cache (e.g. after a campaign is activated/paused)."""
    async with _redis() as r:
        keys = await r.keys("auction:*")
        if keys:
            await r.delete(*keys)
