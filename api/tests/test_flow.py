"""API flow tests — register → expense → approve → balance/report."""

from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def client(tmp_path_factory, monkeypatch_module):
    db_path = tmp_path_factory.mktemp("db") / "test.db"
    monkeypatch_module.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch_module.setenv("SECRET_KEY", "test-secret")

    from fastapi.testclient import TestClient
    from app.db import Base, engine
    from app.main import app

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def monkeypatch_module():
    from _pytest.monkeypatch import MonkeyPatch

    m = MonkeyPatch()
    yield m
    m.undo()


def _register(client, slug: str, email: str = "owner@example.com"):
    res = client.post(
        "/orgs/register",
        json={
            "name": "Acme",
            "slug": slug,
            "currency": "IDR",
            "owner_email": email,
            "owner_name": "Owner",
            "owner_password": "secret12",
        },
    )
    assert res.status_code == 200, res.text
    return res.json()


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_register_expense_approve_balance(client):
    data = _register(client, "flow-1", "owner1@example.com")
    headers = {"Authorization": f"Bearer {data['access_token']}"}

    rec = client.post(
        "/records",
        headers=headers,
        json={"kind": "expense", "amount": 50000, "category": "supplies", "comment": "tape"},
    )
    assert rec.status_code == 200
    body = rec.json()
    assert body["status"] == "pending"
    rid = body["id"]

    pending = client.get("/records/pending", headers=headers)
    assert pending.status_code == 200
    assert any(x["id"] == rid for x in pending.json())

    decided = client.post(
        f"/records/{rid}/decide",
        headers=headers,
        json={"approve": True, "note": "ok"},
    )
    assert decided.status_code == 200
    assert decided.json()["status"] == "approved"

    bal = client.get("/records/balance/me", headers=headers)
    assert bal.status_code == 200
    assert bal.json()["cash_on_hand"] == -50000

    report = client.get("/reports/org", headers=headers)
    assert report.status_code == 200
    assert report.json()["approved_expense_total"] == 50000


def test_employee_cannot_approve(client):
    owner = _register(client, "flow-2", "owner2@example.com")
    oheaders = {"Authorization": f"Bearer {owner['access_token']}"}
    inv = client.post(
        "/orgs/invite",
        headers=oheaders,
        json={
            "email": "emp@example.com",
            "full_name": "Emp",
            "role": "employee",
            "password": "secret12",
        },
    )
    assert inv.status_code == 200

    login = client.post(
        "/auth/login",
        json={
            "email": "emp@example.com",
            "password": "secret12",
            "organization_slug": "flow-2",
        },
    )
    assert login.status_code == 200
    eheaders = {"Authorization": f"Bearer {login.json()['access_token']}"}

    rec = client.post(
        "/records",
        headers=eheaders,
        json={"kind": "expense", "amount": 1000, "category": "other"},
    )
    rid = rec.json()["id"]

    denied = client.post(
        f"/records/{rid}/decide",
        headers=eheaders,
        json={"approve": True},
    )
    assert denied.status_code == 403

    pending = client.get("/records/pending", headers=eheaders)
    assert pending.status_code == 403


def test_tenant_isolation(client):
    a = _register(client, "org-a", "a@example.com")
    b = _register(client, "org-b", "b@example.com")
    ah = {"Authorization": f"Bearer {a['access_token']}"}
    bh = {"Authorization": f"Bearer {b['access_token']}"}

    rec = client.post(
        "/records",
        headers=ah,
        json={"kind": "income", "amount": 999, "category": "sale", "payment_method": "cash"},
    )
    rid = rec.json()["id"]

    other = client.get(f"/records/{rid}", headers=bh)
    assert other.status_code == 404


def test_transfer_creates_two_pending(client):
    owner = _register(client, "flow-xfer", "xfer-owner@example.com")
    oh = {"Authorization": f"Bearer {owner['access_token']}"}
    inv = client.post(
        "/orgs/invite",
        headers=oh,
        json={"email": "xfer-emp@example.com", "full_name": "Emp", "role": "employee", "password": "secret12"},
    )
    assert inv.status_code == 200
    login = client.post(
        "/auth/login",
        json={"email": "xfer-emp@example.com", "password": "secret12", "organization_slug": "flow-xfer"},
    )
    eh = {"Authorization": f"Bearer {login.json()['access_token']}"}
    # invite a second employee as recipient via owner
    inv2 = client.post(
        "/orgs/invite",
        headers=oh,
        json={"email": "xfer-recv@example.com", "full_name": "Recv", "role": "employee", "password": "secret12"},
    )
    assert inv2.status_code == 200
    xfer = client.post(
        "/transfers",
        headers=eh,
        json={"to_email": "xfer-recv@example.com", "amount": 25000, "comment": "change"},
    )
    assert xfer.status_code == 200, xfer.text
    body = xfer.json()
    assert body["sender_record"]["kind"] == "expense"
    assert body["recipient_record"]["kind"] == "income"
    assert body["sender_record"]["status"] == "pending"


def test_expense_payout_resets_spendings(client):
    owner = _register(client, "flow-pay", "pay-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    uid = owner["user"]["id"]
    rec = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 10000,
            "category": "Taxi",
            "payment_source": "my_pocket",
            "purpose": "Office",
        },
    )
    rid = rec.json()["id"]
    client.post(f"/records/{rid}/decide", headers=h, json={"approve": True})
    bal1 = client.get("/records/balance/me", headers=h).json()
    assert bal1["spendings"] == 10000
    pay = client.post(
        "/payouts",
        headers=h,
        json={"user_id": uid, "kind": "expense_payout", "amount": 10000, "payment_method": "cash"},
    )
    assert pay.status_code == 200, pay.text
    bal2 = client.get("/records/balance/me", headers=h).json()
    assert bal2["spendings"] == 0
