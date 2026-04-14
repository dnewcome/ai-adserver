"""Tests for /auction/bid and /auction/click/* endpoints."""
import pytest

from tests.conftest import (
    create_advertiser,
    create_campaign,
    create_impression,
    create_publisher,
    create_zone,
)


async def test_bid_no_fill_unknown_zone(client):
    resp = await client.post(
        "/auction/bid",
        json={"zone_id": "00000000-0000-0000-0000-000000000000", "page_url": "https://example.com"},
    )
    assert resp.status_code == 204


async def test_bid_no_fill_no_campaigns(client, db_session):
    pub = await create_publisher(db_session, email="bid_nofill_pub@test.com")
    zone = await create_zone(db_session, pub.id)
    await db_session.commit()

    resp = await client.post("/auction/bid", json={"zone_id": zone.id})
    assert resp.status_code == 204


async def test_bid_no_fill_zero_balance(client, db_session):
    adv = await create_advertiser(db_session, email="bid_zero_adv@test.com", balance=0.0)
    pub = await create_publisher(db_session, email="bid_zero_pub@test.com")
    await create_campaign(db_session, adv.id)
    zone = await create_zone(db_session, pub.id)
    await db_session.commit()

    resp = await client.post("/auction/bid", json={"zone_id": zone.id})
    assert resp.status_code == 204


async def test_bid_wins(client, db_session):
    adv = await create_advertiser(db_session, email="bid_win_adv@test.com", balance=100.0)
    pub = await create_publisher(db_session, email="bid_win_pub@test.com")
    await create_campaign(db_session, adv.id)
    zone = await create_zone(db_session, pub.id)
    await db_session.commit()

    resp = await client.post("/auction/bid", json={"zone_id": zone.id, "page_url": "https://pub.com/page"})
    assert resp.status_code == 200
    body = resp.json()
    assert "impression_id" in body
    assert "creative" in body
    assert body["cpm_paid"] > 0
    assert "/auction/click/" in body["click_url"]


async def test_bid_second_price_calculation(client, db_session):
    """Winner pays second-highest bid + $0.01."""
    adv = await create_advertiser(db_session, email="spc_adv@test.com", balance=100.0)
    pub = await create_publisher(db_session, email="spc_pub@test.com")
    # Two campaigns: floor CPM 10 and 7. Winner pays 7.01.
    await create_campaign(db_session, adv.id, bid_floor=10.0)
    await create_campaign(db_session, adv.id, bid_floor=7.0)
    zone = await create_zone(db_session, pub.id)
    await db_session.commit()

    resp = await client.post("/auction/bid", json={"zone_id": zone.id})
    assert resp.status_code == 200
    assert resp.json()["cpm_paid"] == pytest.approx(7.01)


async def test_bid_single_campaign_pays_own_floor(client, db_session):
    """With only one bidder, winner pays its own floor + $0.01."""
    adv = await create_advertiser(db_session, email="solo_adv@test.com", balance=100.0)
    pub = await create_publisher(db_session, email="solo_pub@test.com")
    await create_campaign(db_session, adv.id, bid_floor=5.0)
    zone = await create_zone(db_session, pub.id)
    await db_session.commit()

    resp = await client.post("/auction/bid", json={"zone_id": zone.id})
    assert resp.status_code == 200
    assert resp.json()["cpm_paid"] == pytest.approx(5.01)


async def test_bid_deducts_advertiser_balance(client, db_session):
    from sqlalchemy import select
    from models.advertiser import Advertiser

    adv = await create_advertiser(db_session, email="deduct_adv@test.com", balance=50.0)
    pub = await create_publisher(db_session, email="deduct_pub@test.com")
    await create_campaign(db_session, adv.id, bid_floor=5.0)
    zone = await create_zone(db_session, pub.id)
    await db_session.commit()

    await client.post("/auction/bid", json={"zone_id": zone.id})

    result = await db_session.execute(select(Advertiser).where(Advertiser.id == adv.id))
    updated = result.scalar_one()
    assert updated.balance_usd < 50.0


async def test_click_records_and_redirects(client, db_session):
    from sqlalchemy import select
    from models.impression import Impression

    adv = await create_advertiser(db_session, email="click_adv@test.com", balance=100.0)
    pub = await create_publisher(db_session, email="click_pub@test.com")
    camp = await create_campaign(db_session, adv.id)
    zone = await create_zone(db_session, pub.id)
    imp = await create_impression(db_session, zone.id, camp.id)
    await db_session.commit()

    resp = await client.get(f"/auction/click/{imp.id}", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"]

    result = await db_session.execute(select(Impression).where(Impression.id == imp.id))
    updated = result.scalar_one()
    assert updated.clicked is True
    assert updated.clicked_at is not None


async def test_click_idempotent(client, db_session):
    """Clicking the same impression twice does not raise an error."""
    adv = await create_advertiser(db_session, email="click2_adv@test.com", balance=100.0)
    pub = await create_publisher(db_session, email="click2_pub@test.com")
    camp = await create_campaign(db_session, adv.id)
    zone = await create_zone(db_session, pub.id)
    imp = await create_impression(db_session, zone.id, camp.id)
    await db_session.commit()

    await client.get(f"/auction/click/{imp.id}", follow_redirects=False)
    resp2 = await client.get(f"/auction/click/{imp.id}", follow_redirects=False)
    assert resp2.status_code == 302


async def test_click_not_found(client):
    resp = await client.get("/auction/click/00000000-0000-0000-0000-000000000000", follow_redirects=False)
    assert resp.status_code == 404


async def test_bid_run_of_network_zone(client, db_session):
    """A zone with NO categories should match all campaigns (issue #17)."""
    adv = await create_advertiser(db_session, email="ron_adv@test.com", balance=100.0)
    pub = await create_publisher(db_session, email="ron_pub@test.com")
    # Campaign with tech categories
    await create_campaign(db_session, adv.id, categories=["IAB19-18"])
    # Zone with NO categories
    zone = await create_zone(db_session, pub.id, categories=[])
    await db_session.commit()

    resp = await client.post("/auction/bid", json={"zone_id": zone.id})
    assert resp.status_code == 200  # should fill, not 204
