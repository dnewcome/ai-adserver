"""
Unit tests for frequency capping (#13) and budget pacing (#14).
These test the auction behaviour directly through the HTTP bid endpoint
with seeded DB data and a controlled fake Redis.
"""
import pytest
from sqlalchemy import select

from models.advertiser import Advertiser
from tests.conftest import create_advertiser, create_campaign, create_publisher, create_zone


# ---------------------------------------------------------------------------
# Frequency capping
# ---------------------------------------------------------------------------

async def test_freq_cap_allows_up_to_cap(client, db_session, mock_redis):
    """Visitor should see the ad up to frequency_cap times per day."""
    adv = await create_advertiser(db_session, email="freq_allow_adv@test.com", balance=100.0)
    pub = await create_publisher(db_session, email="freq_allow_pub@test.com")
    await create_campaign(db_session, adv.id)  # no cap set — always serves
    zone = await create_zone(db_session, pub.id)
    await db_session.commit()

    for _ in range(5):
        resp = await client.post(
            "/auction/bid", json={"zone_id": zone.id, "visitor_id": "visitor-A"}
        )
        assert resp.status_code == 200


async def test_freq_cap_still_serves_when_all_capped(client, db_session, mock_redis):
    """
    When a visitor has exceeded the cap for ALL campaigns, the auction should
    serve anyway (best-effort — don't punish publishers for returning visitors).
    """
    adv = await create_advertiser(db_session, email="freq_over_adv@test.com", balance=100.0)
    pub = await create_publisher(db_session, email="freq_over_pub@test.com")
    camp = await create_campaign(db_session, adv.id)
    # Manually set a cap of 2 in the DB
    camp.frequency_cap = 2
    zone = await create_zone(db_session, pub.id)
    await db_session.commit()

    vid = "visitor-B"
    # Pre-fill the Redis counter past the cap
    await mock_redis.set(f"freq:{vid}:{camp.id}", "5")

    resp = await client.post("/auction/bid", json={"zone_id": zone.id, "visitor_id": vid})
    # Should still fill (best-effort fallback)
    assert resp.status_code == 200


async def test_freq_cap_no_visitor_id_ignores_cap(client, db_session, mock_redis):
    """Without a visitor_id the freq cap is not checked."""
    adv = await create_advertiser(db_session, email="freq_noid_adv@test.com", balance=100.0)
    pub = await create_publisher(db_session, email="freq_noid_pub@test.com")
    camp = await create_campaign(db_session, adv.id)
    camp.frequency_cap = 1
    zone = await create_zone(db_session, pub.id)
    await db_session.commit()

    # Three bids with no visitor_id — all should win
    for _ in range(3):
        resp = await client.post("/auction/bid", json={"zone_id": zone.id})
        assert resp.status_code == 200


async def test_freq_counter_increments_in_redis(client, db_session, mock_redis):
    """Each winning bid increments the visitor's frequency counter in Redis."""
    adv = await create_advertiser(db_session, email="freq_inc_adv@test.com", balance=100.0)
    pub = await create_publisher(db_session, email="freq_inc_pub@test.com")
    camp = await create_campaign(db_session, adv.id)
    zone = await create_zone(db_session, pub.id)
    await db_session.commit()

    vid = "visitor-C"
    await client.post("/auction/bid", json={"zone_id": zone.id, "visitor_id": vid})
    await client.post("/auction/bid", json={"zone_id": zone.id, "visitor_id": vid})

    count = await mock_redis.get(f"freq:{vid}:{camp.id}")
    assert int(count) == 2


# ---------------------------------------------------------------------------
# Budget pacing
# ---------------------------------------------------------------------------

async def test_pacing_allows_campaign_within_budget(client, db_session, mock_redis):
    """A campaign that hasn't spent much today is not skipped."""
    adv = await create_advertiser(db_session, email="pace_ok_adv@test.com", balance=100.0)
    pub = await create_publisher(db_session, email="pace_ok_pub@test.com")
    camp = await create_campaign(db_session, adv.id)
    camp.daily_budget_usd = 100.0
    zone = await create_zone(db_session, pub.id)
    await db_session.commit()

    # today_spend = 0, well under any pacing target
    resp = await client.post("/auction/bid", json={"zone_id": zone.id})
    assert resp.status_code == 200


async def test_pacing_still_serves_when_all_overpacing(client, db_session, mock_redis):
    """
    When all campaigns are overpacing, the auction should serve anyway
    (best-effort — avoid total no-fill due to pacing).
    """
    import datetime
    from auction.cache import _pace_key

    adv = await create_advertiser(db_session, email="pace_over_adv@test.com", balance=100.0)
    pub = await create_publisher(db_session, email="pace_over_pub@test.com")
    camp = await create_campaign(db_session, adv.id)
    camp.daily_budget_usd = 1.0  # $1/day
    zone = await create_zone(db_session, pub.id)
    await db_session.commit()

    # Pre-fill today's spend way over budget (simulates 300% pacing)
    await mock_redis.set(_pace_key(camp.id), "3.0")

    resp = await client.post("/auction/bid", json={"zone_id": zone.id})
    assert resp.status_code == 200  # best-effort fallback


async def test_pacing_counter_increments_on_win(client, db_session, mock_redis):
    """Winning bid increments the pacing counter by cost-per-impression."""
    import datetime
    from auction.cache import _pace_key

    adv = await create_advertiser(db_session, email="pace_inc_adv@test.com", balance=100.0)
    pub = await create_publisher(db_session, email="pace_inc_pub@test.com")
    camp = await create_campaign(db_session, adv.id, bid_floor=5.0)
    zone = await create_zone(db_session, pub.id)
    await db_session.commit()

    await client.post("/auction/bid", json={"zone_id": zone.id})

    spend = await mock_redis.get(_pace_key(camp.id))
    assert spend is not None
    assert float(spend) > 0
