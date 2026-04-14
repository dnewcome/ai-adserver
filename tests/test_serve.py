"""Tests for GET /serve/{zone_id} — bot filtering, visitor_id, no-fill."""
import pytest

from tests.conftest import create_advertiser, create_campaign, create_publisher, create_zone


async def test_serve_returns_ad(client, db_session):
    adv = await create_advertiser(db_session, email="serve_adv@test.com", balance=100.0)
    pub = await create_publisher(db_session, email="serve_pub@test.com")
    await create_campaign(db_session, adv.id)
    zone = await create_zone(db_session, pub.id)
    await db_session.commit()

    resp = await client.get(f"/serve/{zone.id}?url=https://pub.com/page")
    assert resp.status_code == 200
    body = resp.json()
    assert "impression_id" in body
    assert "creative" in body
    assert "click_url" in body


async def test_serve_no_fill_unknown_zone(client):
    resp = await client.get("/serve/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 204


async def test_serve_no_fill_no_campaigns(client, db_session):
    pub = await create_publisher(db_session, email="serve_nofill@test.com")
    zone = await create_zone(db_session, pub.id)
    await db_session.commit()

    resp = await client.get(f"/serve/{zone.id}")
    assert resp.status_code == 204


async def test_serve_bot_filtering_googlebot(client, db_session):
    """Googlebot UA should get 204 without running an auction."""
    adv = await create_advertiser(db_session, email="bot_adv@test.com", balance=100.0)
    pub = await create_publisher(db_session, email="bot_pub@test.com")
    await create_campaign(db_session, adv.id)
    zone = await create_zone(db_session, pub.id)
    await db_session.commit()

    resp = await client.get(
        f"/serve/{zone.id}",
        headers={"User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"},
    )
    assert resp.status_code == 204


async def test_serve_bot_filtering_curl(client, db_session):
    adv = await create_advertiser(db_session, email="curl_adv@test.com", balance=100.0)
    pub = await create_publisher(db_session, email="curl_pub@test.com")
    await create_campaign(db_session, adv.id)
    zone = await create_zone(db_session, pub.id)
    await db_session.commit()

    resp = await client.get(f"/serve/{zone.id}", headers={"User-Agent": "curl/8.0.1"})
    assert resp.status_code == 204


async def test_serve_real_browser_not_filtered(client, db_session):
    """A realistic browser UA should not be blocked."""
    adv = await create_advertiser(db_session, email="browser_adv@test.com", balance=100.0)
    pub = await create_publisher(db_session, email="browser_pub@test.com")
    await create_campaign(db_session, adv.id)
    zone = await create_zone(db_session, pub.id)
    await db_session.commit()

    resp = await client.get(
        f"/serve/{zone.id}",
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0"},
    )
    assert resp.status_code == 200


async def test_serve_visitor_id_accepted(client, db_session):
    """visitor_id query param is accepted without error."""
    adv = await create_advertiser(db_session, email="vid_adv@test.com", balance=100.0)
    pub = await create_publisher(db_session, email="vid_pub@test.com")
    await create_campaign(db_session, adv.id)
    zone = await create_zone(db_session, pub.id)
    await db_session.commit()

    resp = await client.get(f"/serve/{zone.id}?visitor_id=abc123")
    assert resp.status_code == 200
