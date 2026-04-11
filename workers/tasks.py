"""
Celery tasks for long-running AI pipelines.

Each task uses asyncio.run() to drive async code inside a sync Celery worker.
Results are stored in Redis via the Celery result backend and picked up by
GET /jobs/{job_id}.
"""
import asyncio
import logging

from celery import Task

from workers.celery_app import celery_app

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Base class — shared async runner helper
# ---------------------------------------------------------------------------

class AsyncTask(Task):
    abstract = True

    def run_async(self, coro):
        return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Campaign creation task
# ---------------------------------------------------------------------------

@celery_app.task(
    bind=True,
    base=AsyncTask,
    name="workers.tasks.create_campaign",
    max_retries=2,
    default_retry_delay=10,
)
def create_campaign_task(
    self,
    advertiser_id: str,
    product_url: str,
    daily_budget_usd: float | None = None,
    total_budget_usd: float | None = None,
) -> dict:
    """
    Full pipeline: URL → scrape → brand analysis → creatives → save Campaign row.
    Returns {campaign_id, status} which the jobs endpoint forwards to the caller.
    Image generation is chained as a separate task.
    """
    try:
        return self.run_async(
            _create_campaign_async(
                advertiser_id=advertiser_id,
                product_url=product_url,
                daily_budget_usd=daily_budget_usd,
                total_budget_usd=total_budget_usd,
            )
        )
    except Exception as exc:
        logger.error("create_campaign_task failed: %s", exc)
        raise self.retry(exc=exc)


async def _create_campaign_async(
    advertiser_id: str,
    product_url: str,
    daily_budget_usd: float | None,
    total_budget_usd: float | None,
) -> dict:
    import models  # noqa: F401 — registers all mappers before any query
    from ai.campaign_creator import create_campaign_from_url
    from models.base import task_session
    from models.campaign import Campaign, CampaignStatus

    result = await create_campaign_from_url(product_url)

    async with task_session() as db:
        campaign = Campaign(
            advertiser_id=advertiser_id,
            product_url=result["product_url"],
            brand_name=result.get("brand_name"),
            brand_description=result.get("brand_description"),
            value_propositions=result.get("value_propositions", []),
            target_audience=result.get("target_audience", {}),
            tone_of_voice=result.get("tone_of_voice"),
            suggested_categories=result.get("suggested_categories", []),
            bid_floor_cpm=result.get("bid_floor_cpm"),
            ad_creatives=result.get("ad_creatives", []),
            daily_budget_usd=daily_budget_usd,
            total_budget_usd=total_budget_usd,
            status=CampaignStatus.ACTIVE,
            is_listed=True,
            images_status="pending" if result.get("ad_creatives") else None,
        )
        db.add(campaign)
        await db.commit()
        await db.refresh(campaign)
        campaign_id = campaign.id
        brand_name = campaign.brand_name
        tone = campaign.tone_of_voice

    # Chain image generation as a follow-up task (fire and forget)
    if result.get("ad_creatives"):
        generate_images_task.delay(campaign_id, brand_name, tone)

    return {"campaign_id": campaign_id, "status": "created"}


# ---------------------------------------------------------------------------
# Site analysis task
# ---------------------------------------------------------------------------

@celery_app.task(
    bind=True,
    base=AsyncTask,
    name="workers.tasks.analyze_site",
    max_retries=2,
    default_retry_delay=10,
)
def analyze_site_task(
    self,
    publisher_id: str,
    site_url: str,
    base_url: str = "http://localhost:8000",
) -> dict:
    """
    Scrape + AI analysis → save InventoryZone rows.
    Returns {zone_ids, analysis} for the jobs endpoint.
    """
    try:
        return self.run_async(
            _analyze_site_async(
                publisher_id=publisher_id,
                site_url=site_url,
                base_url=base_url,
            )
        )
    except Exception as exc:
        logger.error("analyze_site_task failed: %s", exc)
        raise self.retry(exc=exc)


async def _analyze_site_async(
    publisher_id: str,
    site_url: str,
    base_url: str,
) -> dict:
    import models  # noqa: F401
    from ai.publisher_analyzer import _generate_serve_tag, analyze_publisher_site
    from models.base import task_session
    from models.publisher import InventoryZone

    result = await analyze_publisher_site(site_url)

    async with task_session() as db:
        zone_ids = []
        for zone in result.get("recommended_zones", []):
            iz = InventoryZone(
                publisher_id=publisher_id,
                name=zone["name"],
                zone_type=zone["zone_type"],
                dimensions=zone.get("dimensions"),
                recommended_cpm_usd=zone.get("recommended_cpm_usd"),
                placement_rationale=zone.get("placement_rationale"),
                categories=zone.get("categories", []),
            )
            db.add(iz)
            await db.flush()   # get the ID before commit
            iz.serve_tag = _generate_serve_tag(iz.id, iz.zone_type, base_url)
            zone_ids.append(iz.id)

        await db.commit()

    return {
        "zone_ids": zone_ids,
        "site_summary": result.get("site_summary"),
        "audience_profile": result.get("audience_profile"),
        "conversion_tips": result.get("conversion_tips", []),
        "estimated_monthly_revenue_usd": result.get("estimated_monthly_revenue_usd"),
        "status": "analyzed",
    }


# ---------------------------------------------------------------------------
# Image generation task (chained from create_campaign_task)
# ---------------------------------------------------------------------------

@celery_app.task(
    bind=True,
    base=AsyncTask,
    name="workers.tasks.generate_images",
    max_retries=1,
    default_retry_delay=5,
)
def generate_images_task(
    self,
    campaign_id: str,
    brand_name: str | None = None,
    tone: str | None = None,
) -> dict:
    try:
        return self.run_async(_generate_images_async(campaign_id, brand_name, tone))
    except Exception as exc:
        logger.error("generate_images_task failed for %s: %s", campaign_id, exc)
        raise self.retry(exc=exc)


async def _generate_images_async(
    campaign_id: str,
    brand_name: str | None,
    tone: str | None,
) -> dict:
    import models  # noqa: F401
    from sqlalchemy import select, update

    from ai.image_gen import generate_images_for_campaign
    from models.base import task_session
    from models.campaign import Campaign

    async with task_session() as db:
        result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
        campaign = result.scalar_one_or_none()
        if not campaign:
            return {"status": "skipped", "reason": "campaign not found"}

        updated_creatives = await generate_images_for_campaign(
            campaign_id=campaign_id,
            brand_name=brand_name,
            tone=tone,
            creatives=campaign.ad_creatives or [],
        )

        await db.execute(
            update(Campaign)
            .where(Campaign.id == campaign_id)
            .values(ad_creatives=updated_creatives, images_status="done")
        )
        await db.commit()

    return {"status": "done", "campaign_id": campaign_id}
