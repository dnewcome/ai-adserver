"""Tests for /track/pixel/* and /track/convert/* endpoints."""
import pytest
from sqlalchemy import select

from models.conversion import Conversion
from tests.conftest import create_advertiser, create_campaign, create_impression, create_publisher, create_zone


async def test_pixel_returns_gif(client, db_session):
    adv = await create_advertiser(db_session, email="pixel_adv@test.com", balance=10.0)
    pub = await create_publisher(db_session, email="pixel_pub@test.com")
    camp = await create_campaign(db_session, adv.id)
    zone = await create_zone(db_session, pub.id)
    imp = await create_impression(db_session, zone.id, camp.id)
    await db_session.commit()

    resp = await client.get(f"/track/pixel/{imp.id}.gif")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/gif"
    # GIF magic bytes
    assert resp.content[:3] == b"GIF"


async def test_pixel_records_conversion(client, db_session):
    adv = await create_advertiser(db_session, email="pixel_rec_adv@test.com", balance=10.0)
    pub = await create_publisher(db_session, email="pixel_rec_pub@test.com")
    camp = await create_campaign(db_session, adv.id)
    zone = await create_zone(db_session, pub.id)
    imp = await create_impression(db_session, zone.id, camp.id)
    await db_session.commit()

    await client.get(f"/track/pixel/{imp.id}.gif?event=signup")

    result = await db_session.execute(
        select(Conversion).where(Conversion.impression_id == imp.id)
    )
    conv = result.scalar_one_or_none()
    assert conv is not None
    assert conv.event_type == "signup"


async def test_pixel_silences_unknown_impression(client):
    """Pixel should still return a GIF even if the impression ID is unknown."""
    resp = await client.get("/track/pixel/00000000-0000-0000-0000-000000000000.gif")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/gif"


async def test_pixel_no_cache_headers(client, db_session):
    adv = await create_advertiser(db_session, email="nocache_adv@test.com", balance=10.0)
    pub = await create_publisher(db_session, email="nocache_pub@test.com")
    camp = await create_campaign(db_session, adv.id)
    zone = await create_zone(db_session, pub.id)
    imp = await create_impression(db_session, zone.id, camp.id)
    await db_session.commit()

    resp = await client.get(f"/track/pixel/{imp.id}.gif")
    assert "no-store" in resp.headers.get("cache-control", "")


async def test_postback_records_conversion(client, db_session):
    adv = await create_advertiser(db_session, email="postback_adv@test.com", balance=10.0)
    pub = await create_publisher(db_session, email="postback_pub@test.com")
    camp = await create_campaign(db_session, adv.id)
    zone = await create_zone(db_session, pub.id)
    imp = await create_impression(db_session, zone.id, camp.id)
    await db_session.commit()

    resp = await client.post(
        f"/track/convert/{imp.id}",
        json={"event_type": "purchase", "event_data": {"order_value": 49.99}},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["impression_id"] == imp.id
    assert body["event_type"] == "purchase"
    assert "conversion_id" in body


async def test_postback_not_found(client):
    resp = await client.post(
        "/track/convert/00000000-0000-0000-0000-000000000000",
        json={"event_type": "purchase"},
    )
    assert resp.status_code == 404


async def test_postback_default_event_type(client, db_session):
    adv = await create_advertiser(db_session, email="default_ev_adv@test.com", balance=10.0)
    pub = await create_publisher(db_session, email="default_ev_pub@test.com")
    camp = await create_campaign(db_session, adv.id)
    zone = await create_zone(db_session, pub.id)
    imp = await create_impression(db_session, zone.id, camp.id)
    await db_session.commit()

    resp = await client.post(f"/track/convert/{imp.id}", json={})
    assert resp.status_code == 201
    assert resp.json()["event_type"] == "conversion"
