"""Tests for POST /auth/register and POST /auth/login."""
import pytest

from tests.conftest import create_advertiser, create_publisher


async def test_register_advertiser(client):
    resp = await client.post("/auth/register", json={
        "email": "newadv@test.com",
        "password": "secret",
        "role": "advertiser",
        "company_name": "Acme",
    })
    assert resp.status_code == 201
    body = resp.json()
    assert body["role"] == "advertiser"
    assert "access_token" in body


async def test_register_publisher(client):
    resp = await client.post("/auth/register", json={
        "email": "newpub@test.com",
        "password": "secret",
        "role": "publisher",
        "site_url": "https://mypub.com",
    })
    assert resp.status_code == 201
    assert resp.json()["role"] == "publisher"


async def test_register_duplicate_email(client):
    payload = {"email": "dup@test.com", "password": "x", "role": "advertiser"}
    await client.post("/auth/register", json=payload)
    resp = await client.post("/auth/register", json=payload)
    assert resp.status_code == 409


async def test_register_duplicate_across_roles(client):
    """Same email cannot be reused even with a different role."""
    await client.post("/auth/register", json={"email": "cross@test.com", "password": "x", "role": "advertiser"})
    resp = await client.post("/auth/register", json={"email": "cross@test.com", "password": "x", "role": "publisher"})
    # login should still succeed as advertiser
    login = await client.post("/auth/login", data={"username": "cross@test.com", "password": "x"})
    assert login.status_code == 200


async def test_login_advertiser(client, db_session):
    await create_advertiser(db_session, email="login_adv@test.com", password="mypass")
    await db_session.commit()

    resp = await client.post("/auth/login", data={"username": "login_adv@test.com", "password": "mypass"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["role"] == "advertiser"
    assert "access_token" in body


async def test_login_publisher(client, db_session):
    await create_publisher(db_session, email="login_pub@test.com", password="pubpass")
    await db_session.commit()

    resp = await client.post("/auth/login", data={"username": "login_pub@test.com", "password": "pubpass"})
    assert resp.status_code == 200
    assert resp.json()["role"] == "publisher"


async def test_login_wrong_password(client, db_session):
    await create_advertiser(db_session, email="wrongpw@test.com", password="correct")
    await db_session.commit()

    resp = await client.post("/auth/login", data={"username": "wrongpw@test.com", "password": "wrong"})
    assert resp.status_code == 401


async def test_login_unknown_email(client):
    resp = await client.post("/auth/login", data={"username": "nobody@test.com", "password": "x"})
    assert resp.status_code == 401
