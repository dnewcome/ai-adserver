"""Tests for /campaigns/* endpoints."""
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import create_advertiser, create_campaign, create_impression, create_zone, create_publisher, get_token


async def test_requires_auth(client):
    assert (await client.get("/campaigns")).status_code == 401
    assert (await client.post("/campaigns/create", json={"product_url": "https://x.com"})).status_code == 401


async def test_list_campaigns_empty(client, db_session):
    await create_advertiser(db_session, email="list_empty@test.com")
    await db_session.commit()
    token = await get_token(client, "list_empty@test.com", "pass")

    resp = await client.get("/campaigns", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_campaigns(client, db_session):
    adv = await create_advertiser(db_session, email="list_camps@test.com")
    await create_campaign(db_session, adv.id)
    await create_campaign(db_session, adv.id)
    await db_session.commit()
    token = await get_token(client, "list_camps@test.com", "pass")

    resp = await client.get("/campaigns", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert len(resp.json()) == 2


async def test_get_campaign(client, db_session):
    adv = await create_advertiser(db_session, email="get_camp@test.com")
    camp = await create_campaign(db_session, adv.id)
    await db_session.commit()
    token = await get_token(client, "get_camp@test.com", "pass")

    resp = await client.get(f"/campaigns/{camp.id}", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == camp.id
    assert body["brand_name"] == "Test Brand"


async def test_get_campaign_not_found(client, db_session):
    await create_advertiser(db_session, email="notfound@test.com")
    await db_session.commit()
    token = await get_token(client, "notfound@test.com", "pass")

    resp = await client.get("/campaigns/does-not-exist", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 404


async def test_get_campaign_wrong_owner(client, db_session):
    adv1 = await create_advertiser(db_session, email="owner1@test.com")
    adv2 = await create_advertiser(db_session, email="owner2@test.com")
    camp = await create_campaign(db_session, adv1.id)
    await db_session.commit()
    token2 = await get_token(client, "owner2@test.com", "pass")

    resp = await client.get(f"/campaigns/{camp.id}", headers={"Authorization": f"Bearer {token2}"})
    assert resp.status_code == 404


async def test_create_campaign_enqueues_job(client, db_session):
    await create_advertiser(db_session, email="create_camp@test.com")
    await db_session.commit()
    token = await get_token(client, "create_camp@test.com", "pass")

    mock_task = MagicMock()
    mock_task.id = "fake-job-id-123"

    with patch("workers.tasks.create_campaign_task.delay", return_value=mock_task) as mock_delay:
        resp = await client.post(
            "/campaigns/create",
            json={"product_url": "https://example.com/product", "daily_budget_usd": 50.0, "frequency_cap": 3},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 202
    body = resp.json()
    assert body["job_id"] == "fake-job-id-123"
    assert body["status"] == "queued"
    assert "/jobs/" in body["poll_url"]

    # Verify frequency_cap was forwarded to the task
    _, kwargs = mock_delay.call_args
    assert kwargs["frequency_cap"] == 3


async def test_campaign_stats_empty(client, db_session):
    adv = await create_advertiser(db_session, email="stats_empty@test.com")
    camp = await create_campaign(db_session, adv.id)
    await db_session.commit()
    token = await get_token(client, "stats_empty@test.com", "pass")

    resp = await client.get(f"/campaigns/{camp.id}/stats", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["totals"]["impressions"] == 0
    assert body["totals"]["clicks"] == 0
    assert body["totals"]["spend_usd"] == 0
    assert body["daily"] == []


async def test_campaign_stats_with_impressions(client, db_session):
    adv = await create_advertiser(db_session, email="stats_data@test.com")
    pub = await create_publisher(db_session, email="stats_pub@test.com")
    camp = await create_campaign(db_session, adv.id)
    zone = await create_zone(db_session, pub.id)

    # 3 impressions, 1 clicked
    await create_impression(db_session, zone.id, camp.id, cpm=5.0)
    await create_impression(db_session, zone.id, camp.id, cpm=5.0, clicked=True)
    await create_impression(db_session, zone.id, camp.id, cpm=5.0)
    await db_session.commit()
    token = await get_token(client, "stats_data@test.com", "pass")

    resp = await client.get(f"/campaigns/{camp.id}/stats", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    totals = resp.json()["totals"]
    assert totals["impressions"] == 3
    assert totals["clicks"] == 1
    assert totals["ctr_pct"] == pytest.approx(33.33)
    assert totals["spend_usd"] == pytest.approx(0.015)  # 3 * 5.0 / 1000
