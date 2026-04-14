"""Tests for /publishers/* endpoints."""
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import create_advertiser, create_campaign, create_impression, create_publisher, create_zone, get_token


async def test_requires_auth(client):
    assert (await client.get("/publishers/zones")).status_code == 401
    assert (await client.post("/publishers/analyze-site", json={"site_url": "https://x.com"})).status_code == 401


async def test_list_zones_empty(client, db_session):
    await create_publisher(db_session, email="zones_empty@test.com")
    await db_session.commit()
    token = await get_token(client, "zones_empty@test.com", "pass")

    resp = await client.get("/publishers/zones", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_zones(client, db_session):
    pub = await create_publisher(db_session, email="list_zones@test.com")
    await create_zone(db_session, pub.id)
    await create_zone(db_session, pub.id)
    await db_session.commit()
    token = await get_token(client, "list_zones@test.com", "pass")

    resp = await client.get("/publishers/zones", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert len(resp.json()) == 2


async def test_get_zone_tag(client, db_session):
    pub = await create_publisher(db_session, email="zone_tag@test.com")
    zone = await create_zone(db_session, pub.id)
    zone.serve_tag = f'<script src="/serve/{zone.id}"></script>'
    await db_session.commit()
    token = await get_token(client, "zone_tag@test.com", "pass")

    resp = await client.get(f"/publishers/zones/{zone.id}/tag", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["zone_id"] == zone.id


async def test_get_zone_tag_wrong_owner(client, db_session):
    pub1 = await create_publisher(db_session, email="tag_owner1@test.com")
    pub2 = await create_publisher(db_session, email="tag_owner2@test.com")
    zone = await create_zone(db_session, pub1.id)
    await db_session.commit()
    token2 = await get_token(client, "tag_owner2@test.com", "pass")

    resp = await client.get(f"/publishers/zones/{zone.id}/tag", headers={"Authorization": f"Bearer {token2}"})
    assert resp.status_code == 404


async def test_analyze_site_enqueues_job(client, db_session):
    await create_publisher(db_session, email="analyze@test.com")
    await db_session.commit()
    token = await get_token(client, "analyze@test.com", "pass")

    mock_task = MagicMock()
    mock_task.id = "site-job-456"

    with patch("workers.tasks.analyze_site_task.delay", return_value=mock_task):
        resp = await client.post(
            "/publishers/analyze-site",
            json={"site_url": "https://mypub.com"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 202
    assert resp.json()["job_id"] == "site-job-456"


async def test_zone_stats_empty(client, db_session):
    pub = await create_publisher(db_session, email="zone_stats_empty@test.com")
    zone = await create_zone(db_session, pub.id)
    await db_session.commit()
    token = await get_token(client, "zone_stats_empty@test.com", "pass")

    resp = await client.get(f"/publishers/zones/{zone.id}/stats", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["zone_id"] == zone.id
    assert body["totals"]["impressions"] == 0
    assert body["totals"]["revenue_usd"] == 0


async def test_zone_stats_with_impressions(client, db_session):
    adv = await create_advertiser(db_session, email="zone_stats_adv@test.com")
    pub = await create_publisher(db_session, email="zone_stats_pub@test.com")
    camp = await create_campaign(db_session, adv.id)
    zone = await create_zone(db_session, pub.id)

    await create_impression(db_session, zone.id, camp.id, cpm=10.0)
    await create_impression(db_session, zone.id, camp.id, cpm=10.0, clicked=True)
    await db_session.commit()
    token = await get_token(client, "zone_stats_pub@test.com", "pass")

    resp = await client.get(f"/publishers/zones/{zone.id}/stats", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    totals = resp.json()["totals"]
    assert totals["impressions"] == 2
    assert totals["clicks"] == 1
    assert totals["revenue_usd"] == pytest.approx(0.02)  # 2 * 10.0 / 1000
