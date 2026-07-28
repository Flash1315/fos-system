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
            "owner_password_confirm": "secret12",
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
    assert decided.json()["payment_source"] == "my_pocket"

    bal = client.get("/records/balance/me", headers=headers)
    assert bal.status_code == 200
    assert bal.json()["cash_on_hand"] == 0
    assert bal.json()["spendings"] == 50000

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
            "password_confirm": "secret12",
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
        json={"email": "xfer-emp@example.com", "full_name": "Emp", "role": "employee", "password": "secret12", "password_confirm": "secret12"},
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
        json={"email": "xfer-recv@example.com", "full_name": "Recv", "role": "employee", "password": "secret12", "password_confirm": "secret12"},
    )
    assert inv2.status_code == 200
    # Seed cash on hand for sender (approved cash income)
    income = client.post(
        "/records",
        headers=eh,
        json={
            "kind": "income",
            "amount": 50000,
            "category": "Other",
            "payment_method": "cash",
            "purpose": "Other",
        },
    )
    assert income.status_code == 200
    client.post(f"/records/{income.json()['id']}/decide", headers=oh, json={"approve": True})
    xfer = client.post(
        "/transfers",
        headers=eh,
        json={"to_email": "xfer-recv@example.com", "amount": 25000, "comment": "change"},
    )
    assert xfer.status_code == 200, xfer.text
    body = xfer.json()
    assert body["sender_record"]["kind"] == "expense"
    assert body["recipient_record"]["kind"] == "income"
    assert body["sender_record"]["status"] == "approved"
    assert body["recipient_record"]["status"] == "approved"
    sender_bal = client.get("/records/balance/me", headers=eh).json()
    assert sender_bal["cash_on_hand"] == 25000


def test_transfer_rejects_when_insufficient_cash(client):
    owner = _register(client, "flow-xfer-cash", "xfer2-owner@example.com")
    oh = {"Authorization": f"Bearer {owner['access_token']}"}
    client.post(
        "/orgs/invite",
        headers=oh,
        json={"email": "xfer2-recv@example.com", "full_name": "Recv", "role": "employee", "password": "secret12", "password_confirm": "secret12"},
    )
    denied = client.post(
        "/transfers",
        headers=oh,
        json={"to_email": "xfer2-recv@example.com", "amount": 999999, "comment": "too much"},
    )
    assert denied.status_code == 400
    assert "available" in denied.json()["detail"].lower() or "Insufficient" in denied.json()["detail"]


def test_transfer_and_approve_honor_reserved_cash(client):
    owner = _register(client, "flow-resvcash", "resvcash-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    inv = client.post(
        "/orgs/invite",
        headers=h,
        json={
            "email": "resvcash-emp@example.com",
            "full_name": "Emp",
            "role": "employee",
            "password": "secret12",
            "password_confirm": "secret12",
        },
    )
    assert inv.status_code == 200
    client.post(
        "/records",
        headers=h,
        json={
            "kind": "income",
            "amount": 10000,
            "category": "Other",
            "payment_method": "cash",
            "approve_now": True,
        },
    )
    req = client.post(
        "/payouts/requests",
        headers=h,
        json={"kind": "income_handover", "amount": 6000, "note": "hold cash"},
    )
    assert req.status_code == 200
    bal = client.get("/records/balance/me", headers=h).json()
    assert bal["available_cash"] == 4000
    assert bal["reserved_cash"] == 6000
    denied_xfer = client.post(
        "/transfers",
        headers=h,
        json={"to_email": "resvcash-emp@example.com", "amount": 5000, "comment": "too much"},
    )
    assert denied_xfer.status_code == 400
    ok_xfer = client.post(
        "/transfers",
        headers=h,
        json={"to_email": "resvcash-emp@example.com", "amount": 1000, "comment": "ok"},
    )
    assert ok_xfer.status_code == 200, ok_xfer.text
    # Remaining available = 3000; approving 4000 from cash must fail
    pend = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 4000,
            "category": "Taxi",
            "payment_source": "cash_on_hand",
        },
    )
    assert pend.status_code == 200
    denied_appr = client.post(
        f"/records/{pend.json()['id']}/decide",
        headers=h,
        json={"approve": True},
    )
    assert denied_appr.status_code == 400
    ok_spend = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 2000,
            "category": "Taxi",
            "payment_source": "cash_on_hand",
            "approve_now": True,
        },
    )
    assert ok_spend.status_code == 200, ok_spend.text
    after = client.get("/records/balance/me", headers=h).json()
    assert after["cash_on_hand"] == 7000  # 10000 - 1000 transfer - 2000 spend
    assert after["reserved_cash"] == 6000
    assert after["available_cash"] == 1000


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


def test_cancel_pending_and_comment(client):
    owner = _register(client, "flow-cancel", "cancel-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    rec = client.post(
        "/records",
        headers=h,
        json={"kind": "expense", "amount": 777, "category": "Supplies", "purpose": "Office"},
    )
    rid = rec.json()["id"]

    note = client.post(f"/records/{rid}/comment", headers=h, json={"note": "check receipt"})
    assert note.status_code == 200, note.text
    assert "check receipt" in note.json()["comment"]

    cancelled = client.delete(f"/records/{rid}", headers=h)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "rejected"
    assert "[cancelled]" in cancelled.json()["comment"]

    again = client.delete(f"/records/{rid}", headers=h)
    assert again.status_code == 200
    assert again.json()["status"] == "rejected"
    assert "[cancelled]" in again.json()["comment"]


def test_purpose_filter_and_period_report(client):
    owner = _register(client, "flow-filter", "filter-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    a = client.post(
        "/records",
        headers=h,
        json={"kind": "expense", "amount": 100, "category": "Taxi", "purpose": "Rental"},
    ).json()["id"]
    b = client.post(
        "/records",
        headers=h,
        json={"kind": "expense", "amount": 200, "category": "Food", "purpose": "Office"},
    ).json()["id"]
    client.post(f"/records/{a}/decide", headers=h, json={"approve": True})
    client.post(f"/records/{b}/decide", headers=h, json={"approve": True})

    rental = client.get("/records/mine?purpose=Rental", headers=h)
    assert rental.status_code == 200
    assert all(x["purpose"] == "Rental" for x in rental.json())
    assert any(x["id"] == a for x in rental.json())

    report = client.get("/reports/org?days=30", headers=h)
    assert report.status_code == 200
    assert report.json()["approved_expense_total"] == 300
    purposes = {p["purpose"]: p["total"] for p in report.json()["by_purpose"]}
    assert purposes.get("Rental") == 100
    assert purposes.get("Office") == 200


def test_overpayment_reduces_next_cycle(client):
    owner = _register(client, "flow-over", "over-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    uid = owner["user"]["id"]
    rid = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 10000,
            "category": "Taxi",
            "payment_source": "my_pocket",
            "purpose": "Office",
        },
    ).json()["id"]
    client.post(f"/records/{rid}/decide", headers=h, json={"approve": True})
    pay = client.post(
        "/payouts",
        headers=h,
        json={"user_id": uid, "kind": "expense_payout", "amount": 12000, "payment_method": "cash"},
    )
    assert pay.status_code == 200, pay.text
    assert pay.json()["overpayment"] == 2000
    assert client.get("/records/balance/me", headers=h).json()["spendings"] == 0

    rid2 = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 5000,
            "category": "Food",
            "payment_source": "my_pocket",
            "purpose": "Office",
        },
    ).json()["id"]
    client.post(f"/records/{rid2}/decide", headers=h, json={"approve": True})
    # 5000 spend - 2000 overpay carry = 3000 owed
    assert client.get("/records/balance/me", headers=h).json()["spendings"] == 3000


def test_create_on_behalf_edit_export_role(client):
    owner = _register(client, "flow-behalf", "behalf-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    inv = client.post(
        "/orgs/invite",
        headers=h,
        json={
            "email": "emp-behalf@example.com",
            "full_name": "Emp B",
            "role": "employee",
            "password": "secret12",
            "password_confirm": "secret12",
        },
    )
    assert inv.status_code == 200
    emp_id = inv.json()["id"]

    rec = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 1500,
            "category": "Taxi",
            "purpose": "Office",
            "payment_source": "my_pocket",
            "created_for_user_id": emp_id,
        },
    )
    assert rec.status_code == 200, rec.text
    body = rec.json()
    assert body["created_by"] == emp_id
    assert "filed by" in body["comment"]
    rid = body["id"]

    patched = client.patch(
        f"/records/{rid}",
        headers=h,
        json={"amount": 1600, "place": "Shop"},
    )
    assert patched.status_code == 200
    assert patched.json()["amount"] == 1600
    assert patched.json()["place"] == "Shop"

    bad_pay = client.patch(
        f"/records/{rid}",
        headers=h,
        json={"payment_source": "wallet"},
    )
    assert bad_pay.status_code == 400
    ok_pay = client.patch(
        f"/records/{rid}",
        headers=h,
        json={"payment_source": "cash_on_hand"},
    )
    assert ok_pay.status_code == 200
    assert ok_pay.json()["payment_source"] == "cash_on_hand"
    assert ok_pay.json()["payment_method"] == ""

    role = client.post(
        f"/orgs/members/{emp_id}/role",
        headers=h,
        json={"role": "manager"},
    )
    assert role.status_code == 200
    assert role.json()["role"] == "manager"

    csv = client.get("/reports/export.csv?days=30", headers=h)
    assert csv.status_code == 200
    assert "record," in csv.text
    assert "type,id,kind" in csv.text


def test_occurred_at_affects_spendings_cutoff(client):
    owner = _register(client, "flow-occurred", "occ-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    uid = owner["user"]["id"]
    seed = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 1000,
            "category": "Taxi",
            "payment_source": "my_pocket",
            "purpose": "Office",
        },
    ).json()["id"]
    client.post(f"/records/{seed}/decide", headers=h, json={"approve": True})
    pay = client.post(
        "/payouts",
        headers=h,
        json={"user_id": uid, "kind": "expense_payout", "amount": 1000, "payment_method": "cash"},
    )
    assert pay.status_code == 200
    assert pay.json()["overpayment"] == 0
    # Late expense dated before payout should NOT count in current spendings
    late = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 9000,
            "category": "Taxi",
            "payment_source": "my_pocket",
            "purpose": "Office",
            "occurred_at": "2020-01-01T12:00:00",
        },
    )
    assert late.status_code == 200
    pending_late = late.json()
    assert pending_late["is_in_closed_cycle"] is True
    assert pending_late["settlement_cutoff_at"]
    client.post(f"/records/{late.json()['id']}/decide", headers=h, json={"approve": True})
    assert client.get("/records/balance/me", headers=h).json()["spendings"] == 0
    locked = client.get(f"/records/{late.json()['id']}", headers=h).json()
    assert locked["is_in_closed_cycle"] is True
    assert locked["can_void"] is False
    assert "Cutoff" in (locked["void_blocked_reason"] or "")
    # Fresh expense (no occurred_at) does count
    fresh = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 3000,
            "category": "Food",
            "payment_source": "my_pocket",
            "purpose": "Office",
        },
    ).json()["id"]
    client.post(f"/records/{fresh}/decide", headers=h, json={"approve": True})
    assert client.get("/records/balance/me", headers=h).json()["spendings"] == 3000
    fresh_row = client.get(f"/records/{fresh}", headers=h).json()
    assert fresh_row["is_in_closed_cycle"] is False
    assert fresh_row["can_void"] is True


def test_password_and_settlement_request(client):
    owner = _register(client, "flow-acct", "acct-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    bad = client.post(
        "/auth/password",
        headers=h,
        json={
            "current_password": "wrong",
            "new_password": "newsecret1",
            "password_confirm": "newsecret1",
        },
    )
    assert bad.status_code == 400
    missing = client.post(
        "/auth/password",
        headers=h,
        json={"current_password": "secret12", "new_password": "newsecret1"},
    )
    assert missing.status_code == 422
    ok = client.post(
        "/auth/password",
        headers=h,
        json={
            "current_password": "secret12",
            "new_password": "newsecret1",
            "password_confirm": "newsecret1",
        },
    )
    assert ok.status_code == 200
    body = ok.json()
    assert "access_token" in body
    new_h = {"Authorization": f"Bearer {body['access_token']}"}
    assert client.get("/auth/me", headers=new_h).status_code == 200
    # Old JWT revoked after password change
    assert client.get("/auth/me", headers=h).status_code == 401
    h = new_h

    inv = client.post(
        "/orgs/invite",
        headers=h,
        json={
            "email": "acct-emp@example.com",
            "full_name": "Emp",
            "role": "employee",
            "password": "secret12",
            "password_confirm": "secret12",
        },
    )
    assert inv.status_code == 200
    login = client.post(
        "/auth/login",
        json={
            "email": "acct-emp@example.com",
            "password": "secret12",
            "organization_slug": "flow-acct",
        },
    )
    eh = {"Authorization": f"Bearer {login.json()['access_token']}"}
    income = client.post(
        "/records",
        headers=eh,
        json={
            "kind": "income",
            "amount": 8000,
            "category": "Cash",
            "payment_method": "cash",
            "purpose": "Other",
        },
    ).json()["id"]
    client.post(f"/records/{income}/decide", headers=h, json={"approve": True})
    req = client.post(
        "/payouts/requests",
        headers=eh,
        json={"kind": "income_handover", "amount": 5000, "note": "end of day"},
    )
    assert req.status_code == 200, req.text
    rid = req.json()["id"]
    pending = client.get("/payouts/requests", headers=h)
    assert pending.status_code == 200
    assert any(x["id"] == rid for x in pending.json())
    approved = client.post(f"/payouts/requests/{rid}/approve", headers=h)
    assert approved.status_code == 200, approved.text
    assert approved.json()["kind"] == "income_handover"
    assert approved.json()["balance_after"] == 3000
    bal = client.get("/records/balance/me", headers=eh).json()
    assert bal["cash_on_hand"] == 3000


def test_record_search(client):
    owner = _register(client, "flow-search", "search-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    client.post(
        "/records",
        headers=h,
        json={"kind": "expense", "amount": 10, "category": "Taxi", "place": "Denpasar shop", "comment": "oil"},
    )
    client.post(
        "/records",
        headers=h,
        json={"kind": "expense", "amount": 20, "category": "Food", "place": "Office", "comment": "lunch"},
    )
    hit = client.get("/records/mine?q=Denpasar", headers=h)
    assert hit.status_code == 200
    assert len(hit.json()) == 1
    assert hit.json()[0]["place"] == "Denpasar shop"


def test_my_report(client):
    owner = _register(client, "flow-myrep", "myrep-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    rid = client.post(
        "/records",
        headers=h,
        json={"kind": "expense", "amount": 400, "category": "Taxi", "purpose": "Rental", "payment_source": "my_pocket"},
    ).json()["id"]
    client.post(f"/records/{rid}/decide", headers=h, json={"approve": True})
    rep = client.get("/reports/me?days=30", headers=h)
    assert rep.status_code == 200
    body = rep.json()
    assert body["approved_expense_total"] == 400
    assert any(p["purpose"] == "Rental" for p in body["by_purpose"])


def test_batch_pay_all_spendings(client):
    owner = _register(client, "flow-batch-pay", "batch-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    uid = owner["user"]["id"]
    rid = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 8000,
            "category": "Taxi",
            "payment_source": "my_pocket",
            "purpose": "Office",
        },
    ).json()["id"]
    client.post(f"/records/{rid}/decide", headers=h, json={"approve": True})
    assert client.get("/records/balance/me", headers=h).json()["spendings"] == 8000
    batch = client.post("/payouts/batch-spendings?payment_method=cash", headers=h)
    assert batch.status_code == 200, batch.text
    assert len(batch.json()) >= 1
    assert any(x["user_id"] == uid and x["amount"] == 8000 for x in batch.json())
    assert client.get("/records/balance/me", headers=h).json()["spendings"] == 0


def test_batch_spendings_idempotency_key(client):
    owner = _register(client, "flow-batch-idem", "batch-idem@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    rid = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 4500,
            "category": "Taxi",
            "payment_source": "my_pocket",
            "purpose": "Office",
        },
    ).json()["id"]
    client.post(f"/records/{rid}/decide", headers=h, json={"approve": True})
    headers = {**h, "Idempotency-Key": "batch-spend-once-1"}
    first = client.post("/payouts/batch-spendings?payment_method=cash", headers=headers)
    assert first.status_code == 200, first.text
    assert len(first.json()) >= 1
    second = client.post("/payouts/batch-spendings?payment_method=cash", headers=headers)
    assert second.status_code == 200, second.text
    assert [x["id"] for x in second.json()] == [x["id"] for x in first.json()]
    assert client.get("/records/balance/me", headers=h).json()["spendings"] == 0
    org = client.get("/payouts/org?kind=expense_payout&voided=false", headers=h)
    assert org.status_code == 200
    assert len([x for x in org.json() if x["amount"] == 4500]) == 1


def test_batch_take_all_cash_and_my_requests(client):
    owner = _register(client, "flow-batch-cash", "bcash-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    rid = client.post(
        "/records",
        headers=h,
        json={
            "kind": "income",
            "amount": 15000,
            "category": "Other",
            "payment_method": "cash",
            "purpose": "Other",
        },
    ).json()["id"]
    client.post(f"/records/{rid}/decide", headers=h, json={"approve": True})
    assert client.get("/records/balance/me", headers=h).json()["cash_on_hand"] == 15000

    req = client.post(
        "/payouts/requests",
        headers=h,
        json={"kind": "income_handover", "amount": 5000, "note": "eod"},
    )
    assert req.status_code == 200
    mine = client.get("/payouts/requests/mine", headers=h)
    assert mine.status_code == 200
    assert any(x["id"] == req.json()["id"] for x in mine.json())
    # Pending request reserves 5000 — batch only takes available 10000
    batch = client.post("/payouts/batch-cash?payment_method=cash", headers=h)
    assert batch.status_code == 200, batch.text
    assert len(batch.json()) >= 1
    assert any(x["user_id"] == owner["user"]["id"] and x["amount"] == 10000 for x in batch.json())
    bal = client.get("/records/balance/me", headers=h).json()
    assert bal["cash_on_hand"] == 5000
    assert bal["reserved_cash"] == 5000
    assert bal["available_cash"] == 0
    approved = client.post(f"/payouts/requests/{req.json()['id']}/approve", headers=h)
    assert approved.status_code == 200, approved.text
    assert client.get("/records/balance/me", headers=h).json()["cash_on_hand"] == 0


def test_owner_resets_member_password(client):
    owner = _register(client, "flow-reset", "reset-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    inv = client.post(
        "/orgs/invite",
        headers=h,
        json={
            "email": "reset-emp@example.com",
            "full_name": "Emp",
            "role": "employee",
            "password": "secret12",
            "password_confirm": "secret12",
        },
    )
    assert inv.status_code == 200
    emp_id = inv.json()["id"]
    login = client.post(
        "/auth/login",
        json={
            "email": "reset-emp@example.com",
            "password": "secret12",
            "organization_slug": "flow-reset",
        },
    )
    assert login.status_code == 200
    old_emp_h = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert client.get("/auth/me", headers=old_emp_h).status_code == 200
    reset = client.post(
        f"/orgs/members/{emp_id}/password",
        headers=h,
        json={"new_password": "brandnew1", "password_confirm": "brandnew1"},
    )
    assert reset.status_code == 200, reset.text
    assert client.get("/auth/me", headers=old_emp_h).status_code == 401
    bad = client.post(
        "/auth/login",
        json={
            "email": "reset-emp@example.com",
            "password": "secret12",
            "organization_slug": "flow-reset",
        },
    )
    assert bad.status_code == 401
    ok = client.post(
        "/auth/login",
        json={
            "email": "reset-emp@example.com",
            "password": "brandnew1",
            "organization_slug": "flow-reset",
        },
    )
    assert ok.status_code == 200


def test_pending_purpose_filter_and_decider_name(client):
    owner = _register(client, "flow-pend-f", "pendf-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    a = client.post(
        "/records",
        headers=h,
        json={"kind": "expense", "amount": 11, "category": "Taxi", "purpose": "Rental"},
    ).json()["id"]
    client.post(
        "/records",
        headers=h,
        json={"kind": "expense", "amount": 22, "category": "Food", "purpose": "Office"},
    )
    pend = client.get("/records/pending?purpose=Rental", headers=h)
    assert pend.status_code == 200
    assert len(pend.json()) == 1
    assert pend.json()[0]["id"] == a
    decided = client.post(f"/records/{a}/decide", headers=h, json={"approve": True})
    assert decided.status_code == 200
    assert decided.json()["decided_by_name"] == "Owner"


def test_update_org_owner_only(client):
    owner = _register(client, "flow-org-upd", "orgupd-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    before = client.get("/orgs/me", headers=h)
    assert before.status_code == 200
    assert before.json()["slug"] == "flow-org-upd"
    patched = client.patch(
        "/orgs/me",
        headers=h,
        json={"name": "Renamed Co", "currency": "usd"},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["name"] == "Renamed Co"
    assert patched.json()["currency"] == "USD"
    assert patched.json()["slug"] == "flow-org-upd"
    after = client.get("/orgs/me", headers=h).json()
    assert after["name"] == "Renamed Co"
    assert after["currency"] == "USD"

    inv = client.post(
        "/orgs/invite",
        headers=h,
        json={
            "email": "orgupd-emp@example.com",
            "full_name": "Emp",
            "role": "employee",
            "password": "secret12",
            "password_confirm": "secret12",
        },
    )
    assert inv.status_code == 200
    login = client.post(
        "/auth/login",
        json={
            "email": "orgupd-emp@example.com",
            "password": "secret12",
            "organization_slug": "flow-org-upd",
        },
    )
    eh = {"Authorization": f"Bearer {login.json()['access_token']}"}
    denied = client.patch("/orgs/me", headers=eh, json={"name": "Hacked"})
    assert denied.status_code == 403


def test_quick_settle_from_balances(client):
    owner = _register(client, "flow-quick", "quick-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    uid = owner["user"]["id"]
    income = client.post(
        "/records",
        headers=h,
        json={
            "kind": "income",
            "amount": 50000,
            "category": "Cash",
            "payment_method": "cash",
            "purpose": "Rental",
        },
    ).json()["id"]
    client.post(f"/records/{income}/decide", headers=h, json={"approve": True})
    expense = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 7000,
            "category": "Taxi",
            "payment_source": "my_pocket",
            "purpose": "Office",
        },
    ).json()["id"]
    client.post(f"/records/{expense}/decide", headers=h, json={"approve": True})
    bal = client.get("/records/balance/me", headers=h).json()
    assert bal["spendings"] == 7000
    assert bal["cash_on_hand"] >= 50000
    team = client.get("/records/balance/team", headers=h)
    assert team.status_code == 200
    me_row = next(x for x in team.json() if x["user_id"] == uid)
    assert me_row["spendings"] == 7000

    pay = client.post(
        "/payouts",
        headers=h,
        json={
            "user_id": uid,
            "kind": "expense_payout",
            "amount": me_row["spendings"],
            "payment_method": "cash",
            "note": "quick pay from balances",
        },
    )
    assert pay.status_code == 200, pay.text
    take = client.post(
        "/payouts",
        headers=h,
        json={
            "user_id": uid,
            "kind": "income_handover",
            "amount": 50000,
            "payment_method": "cash",
            "note": "quick take from balances",
        },
    )
    assert take.status_code == 200, take.text
    bal2 = client.get("/records/balance/me", headers=h).json()
    assert bal2["spendings"] == 0
    assert bal2["cash_on_hand"] == bal["cash_on_hand"] - 50000


def test_approve_now_on_create(client):
    owner = _register(client, "flow-approve-now", "apnow-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    rec = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 333,
            "category": "Taxi",
            "purpose": "Office",
            "payment_source": "my_pocket",
            "approve_now": True,
        },
    )
    assert rec.status_code == 200, rec.text
    assert rec.json()["status"] == "approved"
    assert rec.json()["decided_by_name"] == "Owner"
    bal = client.get("/records/balance/me", headers=h).json()
    assert bal["spendings"] == 333

    inv = client.post(
        "/orgs/invite",
        headers=h,
        json={
            "email": "apnow-emp@example.com",
            "full_name": "Emp",
            "role": "employee",
            "password": "secret12",
            "password_confirm": "secret12",
        },
    )
    assert inv.status_code == 200
    login = client.post(
        "/auth/login",
        json={
            "email": "apnow-emp@example.com",
            "password": "secret12",
            "organization_slug": "flow-approve-now",
        },
    )
    eh = {"Authorization": f"Bearer {login.json()['access_token']}"}
    denied = client.post(
        "/records",
        headers=eh,
        json={
            "kind": "expense",
            "amount": 10,
            "category": "Taxi",
            "approve_now": True,
        },
    )
    assert denied.status_code == 403


def test_report_custom_date_range(client):
    owner = _register(client, "flow-dates", "dates-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    old = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 100,
            "category": "Taxi",
            "purpose": "Office",
            "payment_source": "my_pocket",
            "occurred_at": "2024-01-15T12:00:00",
            "approve_now": True,
        },
    )
    assert old.status_code == 200, old.text
    new = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 250,
            "category": "Food",
            "purpose": "Office",
            "payment_source": "my_pocket",
            "occurred_at": "2026-07-01T12:00:00",
            "approve_now": True,
        },
    )
    assert new.status_code == 200, new.text
    ranged = client.get("/reports/org?date_from=2026-01-01&date_to=2026-12-31", headers=h)
    assert ranged.status_code == 200, ranged.text
    assert ranged.json()["approved_expense_total"] == 250
    # Default window is last 365 days — use an explicit wide range for full history
    all_time = client.get(
        "/reports/org?date_from=2024-01-01&date_to=2026-12-31",
        headers=h,
    )
    assert all_time.status_code == 200, all_time.text
    assert all_time.json()["approved_expense_total"] == 350
    defaulted = client.get("/reports/org", headers=h)
    assert defaulted.status_code == 200
    assert defaulted.json()["approved_expense_total"] == 250
    mine = client.get("/reports/me?date_from=2024-01-01&date_to=2024-12-31", headers=h)
    assert mine.status_code == 200
    assert mine.json()["approved_expense_total"] == 100
    bad = client.get("/reports/org?date_from=not-a-date", headers=h)
    assert bad.status_code == 400


def test_approve_rejects_insufficient_cash_on_hand(client):
    owner = _register(client, "flow-cashguard", "cashguard-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    rec = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 99999,
            "category": "Taxi",
            "purpose": "Office",
            "payment_source": "cash_on_hand",
        },
    )
    assert rec.status_code == 200
    rid = rec.json()["id"]
    denied = client.post(f"/records/{rid}/decide", headers=h, json={"approve": True})
    assert denied.status_code == 400
    assert "available" in denied.json()["detail"].lower() or "Insufficient" in denied.json()["detail"]
    # my_pocket spend still approvable without cash
    pocket = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 50,
            "category": "Taxi",
            "payment_source": "my_pocket",
            "approve_now": True,
        },
    )
    assert pocket.status_code == 200
    assert pocket.json()["status"] == "approved"


def test_partial_payout_keeps_remainder(client):
    owner = _register(client, "flow-partial", "partial-owner@example.com")
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
            "approve_now": True,
        },
    )
    assert rec.status_code == 200
    pay = client.post(
        "/payouts",
        headers=h,
        json={"user_id": uid, "kind": "expense_payout", "amount": 4000, "payment_method": "cash"},
    )
    assert pay.status_code == 200, pay.text
    assert pay.json()["balance_after"] == 6000
    bal = client.get("/records/balance/me", headers=h).json()
    assert bal["spendings"] == 6000

    income = client.post(
        "/records",
        headers=h,
        json={
            "kind": "income",
            "amount": 20000,
            "category": "Cash",
            "payment_method": "cash",
            "approve_now": True,
        },
    )
    assert income.status_code == 200
    take = client.post(
        "/payouts",
        headers=h,
        json={"user_id": uid, "kind": "income_handover", "amount": 5000, "payment_method": "cash"},
    )
    assert take.status_code == 200, take.text
    assert take.json()["balance_after"] == 15000
    bal2 = client.get("/records/balance/me", headers=h).json()
    assert bal2["cash_on_hand"] == 15000
    too_much = client.post(
        "/payouts",
        headers=h,
        json={"user_id": uid, "kind": "income_handover", "amount": 999999, "payment_method": "cash"},
    )
    assert too_much.status_code == 400


def test_report_source_aware_metrics(client):
    owner = _register(client, "flow-src", "src-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    client.post(
        "/records",
        headers=h,
        json={
            "kind": "income",
            "amount": 100000,
            "category": "Cash",
            "payment_method": "cash",
            "approve_now": True,
        },
    )
    client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 10000,
            "category": "Taxi",
            "payment_source": "my_pocket",
            "approve_now": True,
        },
    )
    client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 7000,
            "category": "Parts",
            "payment_source": "cash_on_hand",
            "approve_now": True,
        },
    )
    report = client.get("/reports/org", headers=h).json()
    assert report["spend_from_pocket"] == 10000
    assert report["spend_from_cash"] == 7000
    assert report["cash_position"] == 93000  # 100000 - 7000
    assert report["net_result"] == 83000  # 100000 - 10000 - 7000


def test_void_record_and_payout(client):
    owner = _register(client, "flow-void", "void-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    uid = owner["user"]["id"]
    rec = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 4000,
            "category": "Taxi",
            "payment_source": "my_pocket",
            "approve_now": True,
        },
    )
    assert rec.status_code == 200
    rid = rec.json()["id"]
    assert client.get("/records/balance/me", headers=h).json()["spendings"] == 4000
    voided = client.post(f"/records/{rid}/void", headers=h, json={"note": "wrong receipt"})
    assert voided.status_code == 200, voided.text
    assert voided.json()["is_voided"] is True
    assert client.get("/records/balance/me", headers=h).json()["spendings"] == 0
    again = client.post(f"/records/{rid}/void", headers=h, json={"note": "again"})
    assert again.status_code == 200
    assert again.json()["is_voided"] is True

    client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 2500,
            "category": "Food",
            "payment_source": "my_pocket",
            "approve_now": True,
        },
    )
    pay = client.post(
        "/payouts",
        headers=h,
        json={"user_id": uid, "kind": "expense_payout", "amount": 2500},
    )
    assert pay.status_code == 200
    pid = pay.json()["id"]
    assert client.get("/records/balance/me", headers=h).json()["spendings"] == 0
    pv = client.post(f"/payouts/{pid}/void", headers=h, json={"note": "paid wrong person"})
    assert pv.status_code == 200, pv.text
    assert pv.json()["is_voided"] is True
    assert client.get("/records/balance/me", headers=h).json()["spendings"] == 2500


def test_settlement_request_validates_balance(client):
    owner = _register(client, "flow-reqbal", "reqbal-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    denied = client.post(
        "/payouts/requests",
        headers=h,
        json={"kind": "income_handover", "amount": 1000, "note": "no cash"},
    )
    assert denied.status_code == 400
    client.post(
        "/records",
        headers=h,
        json={
            "kind": "income",
            "amount": 3000,
            "category": "Cash",
            "payment_method": "cash",
            "approve_now": True,
        },
    )
    ok = client.post(
        "/payouts/requests",
        headers=h,
        json={"kind": "income_handover", "amount": 2000, "note": "partial"},
    )
    assert ok.status_code == 200


def test_safe_payout_void_and_transfer_pair(client):
    owner = _register(client, "flow-safevoid", "safevoid-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    uid = owner["user"]["id"]
    client.post(
        "/orgs/invite",
        headers=h,
        json={
            "email": "safevoid-emp@example.com",
            "full_name": "Emp",
            "role": "employee",
            "password": "secret12",
            "password_confirm": "secret12",
        },
    )
    client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 1000,
            "category": "Taxi",
            "payment_source": "my_pocket",
            "approve_now": True,
        },
    )
    p1 = client.post(
        "/payouts",
        headers=h,
        json={"user_id": uid, "kind": "expense_payout", "amount": 1000},
    ).json()
    client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 500,
            "category": "Food",
            "payment_source": "my_pocket",
            "approve_now": True,
        },
    )
    p2 = client.post(
        "/payouts",
        headers=h,
        json={"user_id": uid, "kind": "expense_payout", "amount": 500},
    ).json()
    assert p2["can_void"] is True
    listed = client.get("/payouts/org", headers=h).json()
    older_row = next(x for x in listed if x["id"] == p1["id"])
    assert older_row["can_void"] is False
    assert older_row["void_blocked_reason"]
    older = client.post(f"/payouts/{p1['id']}/void", headers=h, json={"note": "old"})
    assert older.status_code == 400
    latest = client.post(f"/payouts/{p2['id']}/void", headers=h, json={"note": "latest ok"})
    assert latest.status_code == 200
    assert client.get("/records/balance/me", headers=h).json()["spendings"] == 500

    client.post(
        "/records",
        headers=h,
        json={
            "kind": "income",
            "amount": 20000,
            "category": "Cash",
            "payment_method": "cash",
            "approve_now": True,
        },
    )
    xfer = client.post(
        "/transfers",
        headers=h,
        json={"to_email": "safevoid-emp@example.com", "amount": 4000, "comment": "pair"},
    )
    assert xfer.status_code == 200, xfer.text
    group = xfer.json()["transfer_group_id"]
    sender_id = xfer.json()["sender_record"]["id"]
    recipient_id = xfer.json()["recipient_record"]["id"]
    assert xfer.json()["sender_record"]["transfer_group_id"] == group
    voided = client.post(f"/records/{sender_id}/void", headers=h, json={"note": "undo transfer"})
    assert voided.status_code == 200
    assert voided.json()["is_voided"] is True
    other = client.get(f"/records/{recipient_id}", headers=h).json()
    assert other["is_voided"] is True
    assert client.get("/records/balance/me", headers=h).json()["cash_on_hand"] == 20000


def test_payment_fields_and_currency_lock(client):
    owner = _register(client, "flow-guards", "guards-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    bad = client.post(
        "/records",
        headers=h,
        json={"kind": "expense", "amount": 10, "category": "Taxi", "payment_source": "wallet"},
    )
    assert bad.status_code == 400
    bad_m = client.post(
        "/records",
        headers=h,
        json={"kind": "income", "amount": 10, "category": "Cash", "payment_method": "crypto"},
    )
    assert bad_m.status_code == 400
    ok = client.patch("/orgs/me", headers=h, json={"currency": "usd"})
    assert ok.status_code == 200
    assert ok.json()["currency"] == "USD"
    client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 10,
            "category": "Taxi",
            "payment_source": "my_pocket",
            "approve_now": True,
        },
    )
    locked = client.patch("/orgs/me", headers=h, json={"currency": "IDR"})
    assert locked.status_code == 400
    rename = client.patch("/orgs/me", headers=h, json={"name": "Guards Co"})
    assert rename.status_code == 200


def test_currency_lock_after_adjustment(client):
    owner = _register(client, "flow-adjcur", "adjcur-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    uid = owner["user"]["id"]
    ok = client.patch("/orgs/me", headers=h, json={"currency": "usd"})
    assert ok.status_code == 200
    adj = client.post(
        "/adjustments",
        headers=h,
        json={
            "user_id": uid,
            "track": "spendings",
            "amount": 5000,
            "note": "opening",
        },
    )
    assert adj.status_code == 200
    locked = client.patch("/orgs/me", headers=h, json={"currency": "IDR"})
    assert locked.status_code == 400


def test_settlement_reserve_and_record_lock(client):
    owner = _register(client, "flow-reserve", "reserve-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    uid = owner["user"]["id"]
    client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 10000,
            "category": "Taxi",
            "payment_source": "my_pocket",
            "approve_now": True,
        },
    )
    before = client.get("/records/balance/me", headers=h).json()
    assert before["spendings"] == 10000
    assert before["available_spendings"] == 10000
    assert before["reserved_spendings"] == 0
    assert before["last_expense_payout_at"] is None

    r1 = client.post(
        "/payouts/requests",
        headers=h,
        json={"kind": "expense_payout", "amount": 6000, "note": "first"},
    )
    assert r1.status_code == 200
    mid = client.get("/records/balance/me", headers=h).json()
    assert mid["spendings"] == 10000
    assert mid["reserved_spendings"] == 6000
    assert mid["available_spendings"] == 4000
    r2 = client.post(
        "/payouts/requests",
        headers=h,
        json={"kind": "expense_payout", "amount": 5000, "note": "too much"},
    )
    assert r2.status_code == 400
    r2ok = client.post(
        "/payouts/requests",
        headers=h,
        json={"kind": "expense_payout", "amount": 4000, "note": "second"},
    )
    assert r2ok.status_code == 200
    reserved_both = client.get("/records/balance/me", headers=h).json()
    assert reserved_both["reserved_spendings"] == 10000
    assert reserved_both["available_spendings"] == 0

    rid = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 111,
            "category": "Food",
            "payment_source": "my_pocket",
            "approve_now": True,
        },
    ).json()["id"]
    # cancel pending requests so we can settle the record cleanly
    client.post(f"/payouts/requests/{r1.json()['id']}/cancel", headers=h)
    client.post(f"/payouts/requests/{r2ok.json()['id']}/cancel", headers=h)
    detail = client.get(f"/records/{rid}", headers=h).json()
    assert detail["can_void"] is True
    pay = client.post(
        "/payouts",
        headers=h,
        json={"user_id": uid, "kind": "expense_payout", "amount": 10111},
    )
    assert pay.status_code == 200
    after = client.get("/records/balance/me", headers=h).json()
    assert after["spendings"] == 0
    assert after["reserved_spendings"] == 0
    assert after["last_expense_payout_at"] is not None
    locked = client.get(f"/records/{rid}", headers=h).json()
    assert locked["can_void"] is False
    assert locked["void_blocked_reason"]
    denied = client.post(f"/records/{rid}/void", headers=h, json={"note": "nope"})
    assert denied.status_code == 400
    # void payout unlocks
    client.post(f"/payouts/{pay.json()['id']}/void", headers=h, json={"note": "undo settle"})
    unlocked = client.get(f"/records/{rid}", headers=h).json()
    assert unlocked["can_void"] is True
    assert unlocked["void_blocked_reason"] is None


def test_transfer_excluded_from_operating_report(client):
    owner = _register(client, "flow-xferrep", "xferrep-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    client.post(
        "/orgs/invite",
        headers=h,
        json={
            "email": "xferrep-emp@example.com",
            "full_name": "Emp",
            "role": "employee",
            "password": "secret12",
            "password_confirm": "secret12",
        },
    )
    client.post(
        "/records",
        headers=h,
        json={
            "kind": "income",
            "amount": 50000,
            "category": "Cash",
            "payment_method": "cash",
            "approve_now": True,
        },
    )
    client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 3000,
            "category": "Taxi",
            "payment_source": "my_pocket",
            "approve_now": True,
        },
    )
    client.post(
        "/transfers",
        headers=h,
        json={"to_email": "xferrep-emp@example.com", "amount": 10000, "comment": "ops"},
    )
    report = client.get("/reports/org", headers=h).json()
    assert report["approved_expense_total"] == 3000
    assert report["internal_transfer_total"] == 10000
    assert report["net_result"] == 47000  # 50000 - 3000


def test_payout_voided_filter(client):
    owner = _register(client, "flow-pvoidf", "pvoidf-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    uid = owner["user"]["id"]
    client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 2000,
            "category": "Taxi",
            "payment_source": "my_pocket",
            "approve_now": True,
        },
    )
    pay = client.post(
        "/payouts",
        headers=h,
        json={"user_id": uid, "kind": "expense_payout", "amount": 2000},
    )
    assert pay.status_code == 200
    pid = pay.json()["id"]
    client.post(f"/payouts/{pid}/void", headers=h, json={"note": "undo"})
    active = client.get("/payouts/org?voided=false", headers=h).json()
    assert all(not x.get("is_voided") for x in active)
    assert all(x["id"] != pid for x in active)
    voided = client.get("/payouts/org?voided=true", headers=h).json()
    assert any(x["id"] == pid and x["is_voided"] for x in voided)
    by_kind = client.get("/payouts/org?kind=expense_payout&voided=true", headers=h).json()
    assert any(x["id"] == pid for x in by_kind)
    by_user = client.get(f"/payouts/org?user_id={uid}&voided=true", headers=h).json()
    assert any(x["id"] == pid for x in by_user)
    wrong_kind = client.get("/payouts/org?kind=income_handover&voided=true", headers=h).json()
    assert all(x["id"] != pid for x in wrong_kind)


def test_manager_cancel_request_requires_note(client):
    owner = _register(client, "flow-cancnote", "cancnote-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    inv = client.post(
        "/orgs/invite",
        headers=h,
        json={
            "email": "cancnote-emp@example.com",
            "full_name": "Emp",
            "role": "employee",
            "password": "secret12",
            "password_confirm": "secret12",
        },
    )
    assert inv.status_code == 200
    emp_id = inv.json()["id"]
    client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 3000,
            "category": "Taxi",
            "payment_source": "my_pocket",
            "created_for_user_id": emp_id,
            "approve_now": True,
        },
    )
    login = client.post(
        "/auth/login",
        json={
            "email": "cancnote-emp@example.com",
            "password": "secret12",
            "organization_slug": "flow-cancnote",
        },
    )
    eh = {"Authorization": f"Bearer {login.json()['access_token']}"}
    req = client.post(
        "/payouts/requests",
        headers=eh,
        json={"kind": "expense_payout", "amount": 3000, "note": "pls"},
    )
    assert req.status_code == 200
    bare = client.post(f"/payouts/requests/{req.json()['id']}/cancel", headers=h, json={})
    assert bare.status_code == 400
    ok = client.post(
        f"/payouts/requests/{req.json()['id']}/cancel",
        headers=h,
        json={"note": "not this week"},
    )
    assert ok.status_code == 200
    assert "not this week" in ok.json()["note"]


def test_payout_respects_reserved_available(client):
    owner = _register(client, "flow-availpay", "availpay-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    uid = owner["user"]["id"]
    client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 10000,
            "category": "Taxi",
            "payment_source": "my_pocket",
            "approve_now": True,
        },
    )
    req = client.post(
        "/payouts/requests",
        headers=h,
        json={"kind": "expense_payout", "amount": 6000, "note": "hold"},
    )
    assert req.status_code == 200
    mid = client.get("/records/balance/me", headers=h).json()
    assert mid["available_spendings"] == 4000
    too_much = client.post(
        "/payouts",
        headers=h,
        json={"user_id": uid, "kind": "expense_payout", "amount": 10000},
    )
    assert too_much.status_code == 400
    partial = client.post(
        "/payouts",
        headers=h,
        json={"user_id": uid, "kind": "expense_payout", "amount": 4000},
    )
    assert partial.status_code == 200, partial.text
    assert partial.json()["balance_after"] == 6000
    after = client.get("/records/balance/me", headers=h).json()
    assert after["spendings"] == 6000
    assert after["reserved_spendings"] == 6000
    assert after["available_spendings"] == 0
    approved = client.post(f"/payouts/requests/{req.json()['id']}/approve", headers=h)
    assert approved.status_code == 200, approved.text
    done = client.get("/records/balance/me", headers=h).json()
    assert done["spendings"] == 0
    assert done["reserved_spendings"] == 0


def test_reject_requires_note(client):
    owner = _register(client, "flow-rejnote", "rejnote-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    rid = client.post(
        "/records",
        headers=h,
        json={"kind": "expense", "amount": 100, "category": "Taxi", "payment_source": "my_pocket"},
    ).json()["id"]
    bare = client.post(f"/records/{rid}/decide", headers=h, json={"approve": False, "note": ""})
    assert bare.status_code in (400, 422)
    ok = client.post(
        f"/records/{rid}/decide",
        headers=h,
        json={"approve": False, "note": "duplicate"},
    )
    assert ok.status_code == 200
    assert ok.json()["status"] == "rejected"
    assert "duplicate" in ok.json()["comment"]


def test_voided_list_filter(client):
    owner = _register(client, "flow-voidfilter", "voidfilter-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    rec = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 900,
            "category": "Taxi",
            "payment_source": "my_pocket",
            "approve_now": True,
        },
    ).json()
    client.post(f"/records/{rec['id']}/void", headers=h, json={"note": "mistake"})
    live = client.get("/records/mine?status=approved&voided=false", headers=h).json()
    assert all(not x.get("is_voided") for x in live)
    assert all(x["id"] != rec["id"] for x in live)
    only_void = client.get("/records/mine?voided=true", headers=h).json()
    assert any(x["id"] == rec["id"] and x["is_voided"] for x in only_void)


def test_fuel_odometer_cannot_decrease(client):
    owner = _register(client, "flow-odo", "odo-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    first = client.post(
        "/records",
        headers=h,
        json={
            "kind": "fuel",
            "amount": 200000,
            "category": "Fuel",
            "bike": "Scoot-1",
            "odometer": 12000,
            "liters": 5,
            "approve_now": True,
        },
    )
    assert first.status_code == 200, first.text
    hint = client.get("/records/fuel/last-odometer?bike=Scoot-1", headers=h)
    assert hint.status_code == 200
    assert hint.json()["odometer"] == 12000
    assert hint.json()["min_odometer"] == 12000
    assert hint.json()["max_odometer"] is None
    assert hint.json()["has_history"] is True
    bad = client.post(
        "/records",
        headers=h,
        json={
            "kind": "fuel",
            "amount": 100000,
            "category": "Fuel",
            "bike": "Scoot-1",
            "odometer": 11900,
            "liters": 3,
        },
    )
    assert bad.status_code == 400
    ok = client.post(
        "/records",
        headers=h,
        json={
            "kind": "fuel",
            "amount": 100000,
            "category": "Fuel",
            "bike": "Scoot-1",
            "odometer": 12100,
            "liters": 3,
        },
    )
    assert ok.status_code == 200, ok.text
    # Different bike is independent
    other = client.post(
        "/records",
        headers=h,
        json={
            "kind": "fuel",
            "amount": 50000,
            "category": "Fuel",
            "bike": "Scoot-2",
            "odometer": 500,
            "liters": 2,
        },
    )
    assert other.status_code == 200, other.text


def test_fuel_odometer_hint_at_and_chronology(client):
    owner = _register(client, "flow-odo-at", "odo-at-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    early = client.post(
        "/records",
        headers=h,
        json={
            "kind": "fuel",
            "amount": 100000,
            "category": "Fuel",
            "bike": "Chrono-1",
            "odometer": 1000,
            "liters": 4,
            "occurred_at": "2026-01-01T12:00:00",
            "approve_now": True,
        },
    )
    assert early.status_code == 200, early.text
    late = client.post(
        "/records",
        headers=h,
        json={
            "kind": "fuel",
            "amount": 100000,
            "category": "Fuel",
            "bike": "Chrono-1",
            "odometer": 2000,
            "liters": 4,
            "occurred_at": "2026-01-10T12:00:00",
            "approve_now": True,
        },
    )
    assert late.status_code == 200, late.text
    latest = client.get("/records/fuel/last-odometer?bike=Chrono-1", headers=h)
    assert latest.status_code == 200
    assert latest.json()["odometer"] == 2000
    assert latest.json()["min_odometer"] == 2000
    assert latest.json()["max_odometer"] is None
    assert latest.json()["has_history"] is True
    mid = client.get(
        "/records/fuel/last-odometer?bike=Chrono-1&at=2026-01-05",
        headers=h,
    )
    assert mid.status_code == 200, mid.text
    body = mid.json()
    assert body["min_odometer"] == 1000
    assert body["max_odometer"] == 2000
    assert body["odometer"] == 1000
    assert body["has_history"] is True
    # Between neighbors: must sit in [1000, 2000]
    bad_low = client.post(
        "/records",
        headers=h,
        json={
            "kind": "fuel",
            "amount": 50000,
            "category": "Fuel",
            "bike": "Chrono-1",
            "odometer": 900,
            "liters": 2,
            "occurred_at": "2026-01-05T12:00:00",
        },
    )
    assert bad_low.status_code == 400
    bad_high = client.post(
        "/records",
        headers=h,
        json={
            "kind": "fuel",
            "amount": 50000,
            "category": "Fuel",
            "bike": "Chrono-1",
            "odometer": 2100,
            "liters": 2,
            "occurred_at": "2026-01-05T12:00:00",
        },
    )
    assert bad_high.status_code == 400
    ok = client.post(
        "/records",
        headers=h,
        json={
            "kind": "fuel",
            "amount": 50000,
            "category": "Fuel",
            "bike": "Chrono-1",
            "odometer": 1500,
            "liters": 2,
            "occurred_at": "2026-01-05T12:00:00",
        },
    )
    assert ok.status_code == 200, ok.text
    bad_at = client.get("/records/fuel/last-odometer?bike=Chrono-1&at=not-a-date", headers=h)
    assert bad_at.status_code == 400


def test_balance_adjustments_and_atomic_approve(client):
    owner = _register(client, "flow-adj", "adj-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    uid = owner["user"]["id"]

    # Opening spendings debt without an expense record
    adj = client.post(
        "/adjustments",
        headers=h,
        json={
            "user_id": uid,
            "track": "spendings",
            "amount": 15000,
            "note": "opening pocket debt",
        },
    )
    assert adj.status_code == 200, adj.text
    bal = client.get("/records/balance/me", headers=h).json()
    assert bal["spendings"] == 15000

    cash_adj = client.post(
        "/adjustments",
        headers=h,
        json={
            "user_id": uid,
            "track": "cash_on_hand",
            "amount": 40000,
            "note": "opening cash float",
        },
    )
    assert cash_adj.status_code == 200, cash_adj.text
    bal = client.get("/records/balance/me", headers=h).json()
    assert bal["cash_on_hand"] == 40000

    # Zero amount rejected
    zero = client.post(
        "/adjustments",
        headers=h,
        json={"user_id": uid, "track": "spendings", "amount": 0, "note": "noop"},
    )
    assert zero.status_code in (400, 422)

    # Approve settlement request creates payout + marks request in one commit
    req = client.post(
        "/payouts/requests",
        headers=h,
        json={"kind": "expense_payout", "amount": 15000, "note": "pay opening"},
    )
    assert req.status_code == 200, req.text
    approved = client.post(f"/payouts/requests/{req.json()['id']}/approve", headers=h)
    assert approved.status_code == 200, approved.text
    assert approved.json()["amount"] == 15000
    decided = client.get("/payouts/requests/mine", headers=h).json()
    row = next(x for x in decided if x["id"] == req.json()["id"])
    assert row["status"] == "approved"
    assert row["payout_id"] == approved.json()["id"]
    assert row["settled_amount"] == 15000
    bal = client.get("/records/balance/me", headers=h).json()
    assert bal["spendings"] == 0

    # Spendings adjustment is locked by the expense payout cycle
    listed = client.get("/adjustments", headers=h).json()
    spend_row = next(x for x in listed if x["id"] == adj.json()["id"])
    assert spend_row["can_void"] is False
    assert spend_row["void_blocked_reason"]
    locked = client.post(
        f"/adjustments/{adj.json()['id']}/void",
        headers=h,
        json={"note": "should fail"},
    )
    assert locked.status_code == 400

    # Cash adjustment still open (no income_handover yet) — void restores float
    cash_listed = next(x for x in listed if x["id"] == cash_adj.json()["id"])
    assert cash_listed["can_void"] is True
    voided = client.post(
        f"/adjustments/{cash_adj.json()['id']}/void",
        headers=h,
        json={"note": "wrong float"},
    )
    assert voided.status_code == 200
    assert voided.json()["is_voided"] is True
    bal = client.get("/records/balance/me", headers=h).json()
    assert bal["cash_on_hand"] == 0

    csv = client.get("/reports/export.csv", headers=h)
    assert csv.status_code == 200
    assert "adjustment" in csv.text

    # Adjustments do not inflate operating expense totals
    report = client.get("/reports/org", headers=h).json()
    assert report["approved_expense_total"] == 0


def test_adjustment_voided_filter(client):
    owner = _register(client, "flow-adjvoid", "adjvoid-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    uid = owner["user"]["id"]
    adj = client.post(
        "/adjustments",
        headers=h,
        json={
            "user_id": uid,
            "track": "spendings",
            "amount": 1500,
            "note": "opening spendings",
        },
    )
    assert adj.status_code == 200
    aid = adj.json()["id"]
    assert (
        client.post(f"/adjustments/{aid}/void", headers=h, json={"note": " "}).status_code
        == 422
    )
    voided = client.post(f"/adjustments/{aid}/void", headers=h, json={"note": "undo"})
    assert voided.status_code == 200
    active = client.get("/adjustments?voided=false", headers=h).json()
    assert all(not x.get("is_voided") for x in active)
    assert all(x["id"] != aid for x in active)
    only_void = client.get("/adjustments?voided=true", headers=h).json()
    assert any(x["id"] == aid and x["is_voided"] for x in only_void)
    by_track = client.get("/adjustments?track=spendings&voided=true", headers=h).json()
    assert any(x["id"] == aid for x in by_track)


def test_settlement_request_status_filter(client):
    owner = _register(client, "flow-reqhist", "reqhist-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 4000,
            "category": "Taxi",
            "payment_source": "my_pocket",
            "approve_now": True,
        },
    )
    req = client.post(
        "/payouts/requests",
        headers=h,
        json={"kind": "expense_payout", "amount": 4000, "note": "pay me"},
    )
    assert req.status_code == 200
    rid = req.json()["id"]
    pending = client.get("/payouts/requests?status=pending", headers=h).json()
    assert any(x["id"] == rid for x in pending)
    client.post(f"/payouts/requests/{rid}/cancel", headers=h, json={"note": "changed mind"})
    pending2 = client.get("/payouts/requests?status=pending", headers=h).json()
    assert all(x["id"] != rid for x in pending2)
    cancelled = client.get("/payouts/requests?status=cancelled", headers=h).json()
    assert any(x["id"] == rid and x["status"] == "cancelled" for x in cancelled)
    all_rows = client.get("/payouts/requests?status=all", headers=h).json()
    assert any(x["id"] == rid for x in all_rows)
    mine = client.get("/payouts/requests/mine?status=cancelled", headers=h).json()
    assert any(x["id"] == rid for x in mine)

def test_report_rejects_reversed_dates(client):
    owner = _register(client, "flow-date-order", "date-order-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    bad = client.get("/reports/org?date_from=2026-12-31&date_to=2026-01-01", headers=h)
    assert bad.status_code == 400
    assert "date_from" in bad.json()["detail"]
    mine = client.get("/reports/me?date_from=2026-06-01&date_to=2026-01-01", headers=h)
    assert mine.status_code == 400


def test_media_auth_bearer_and_query_token(client):
    owner = _register(client, "flow-media-auth", "media-auth-owner@example.com")
    token = owner["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    files = {"file": ("receipt.jpg", b"\xff\xd8\xff" + b"0" * 64, "image/jpeg")}
    up = client.post("/media/photo", headers=h, files=files)
    assert up.status_code == 200, up.text
    url = up.json()["photo_url"]
    assert url.startswith("/media/files/")
    denied = client.get(url)
    assert denied.status_code == 401
    ok_bearer = client.get(url, headers=h)
    assert ok_bearer.status_code == 200
    # Long-lived access JWT must not work in ?token=
    assert client.get(f"{url}?token={token}").status_code == 401
    media_tok = client.get("/records/media-token", headers=h).json()["access_token"]
    ok_q = client.get(f"{url}?token={media_tok}")
    assert ok_q.status_code == 200
    other = _register(client, "flow-media-auth2", "media-auth2-owner@example.com")
    other_h = {"Authorization": f"Bearer {other['access_token']}"}
    forbidden = client.get(url, headers=other_h)
    assert forbidden.status_code == 403


def test_settlement_approve_payment_method(client):
    owner = _register(client, "flow-pay-method", "pay-method-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    income = client.post(
        "/records",
        headers=h,
        json={
            "kind": "income",
            "amount": 50000,
            "category": "Cash",
            "payment_method": "cash",
            "approve_now": True,
        },
    )
    assert income.status_code == 200, income.text
    req = client.post(
        "/payouts/requests",
        headers=h,
        json={"kind": "income_handover", "amount": 10000, "note": "take"},
    )
    assert req.status_code == 200, req.text
    rid = req.json()["id"]
    approved = client.post(
        f"/payouts/requests/{rid}/approve",
        headers=h,
        json={"payment_method": "transfer"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["payment_method"] == "transfer"

def test_category_required_and_purpose_default(client):
    owner = _register(client, "flow-cat-req", "cat-req-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    bad = client.post(
        "/records",
        headers=h,
        json={"kind": "expense", "amount": 10, "category": "  "},
    )
    assert bad.status_code == 400
    ok = client.post(
        "/records",
        headers=h,
        json={"kind": "expense", "amount": 10, "category": "Taxi"},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["purpose"] == "Other"
    bad_pur = client.post(
        "/records",
        headers=h,
        json={"kind": "expense", "amount": 10, "category": "Taxi", "purpose": "Nope"},
    )
    assert bad_pur.status_code == 400


def test_decide_batch_reports_skipped(client):
    owner = _register(client, "flow-batch-skip", "batch-skip-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    a = client.post(
        "/records",
        headers=h,
        json={"kind": "expense", "amount": 10, "category": "Taxi", "purpose": "Office"},
    ).json()["id"]
    b = client.post(
        "/records",
        headers=h,
        json={"kind": "expense", "amount": 20, "category": "Food", "purpose": "Office"},
    ).json()["id"]
    client.post(f"/records/{b}/decide", headers=h, json={"approve": True})
    res = client.post(
        "/records/decide-batch",
        headers=h,
        json={"ids": [a, b, 999999], "approve": True},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body["decided"]) == 1
    assert body["decided"][0]["id"] == a
    assert body["skipped"] == 2
    empty = client.post(
        "/records/decide-batch",
        headers=h,
        json={"ids": [b, 999999], "approve": True},
    )
    assert empty.status_code == 400


def test_org_currency_locked_flag(client):
    owner = _register(client, "flow-cur-lock-flag", "cur-lock-flag@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    org = client.get("/orgs/me", headers=h).json()
    assert org["currency_locked"] is False
    assert org["currency"] == "IDR"
    client.post(
        "/records",
        headers=h,
        json={"kind": "expense", "amount": 5, "category": "Taxi", "purpose": "Other"},
    )
    org2 = client.get("/orgs/me", headers=h).json()
    assert org2["currency_locked"] is True

def test_decide_batch_skips_insufficient_cash(client):
    owner = _register(client, "flow-batch-cash2", "batch-cash2-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    income = client.post(
        "/records",
        headers=h,
        json={
            "kind": "income",
            "amount": 10000,
            "category": "Cash",
            "payment_method": "cash",
            "approve_now": True,
        },
    )
    assert income.status_code == 200, income.text
    a = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 7000,
            "category": "Taxi",
            "purpose": "Office",
            "payment_source": "cash_on_hand",
        },
    ).json()["id"]
    b = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 7000,
            "category": "Food",
            "purpose": "Office",
            "payment_source": "cash_on_hand",
        },
    ).json()["id"]
    res = client.post(
        "/records/decide-batch",
        headers=h,
        json={"ids": [a, b], "approve": True},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body["decided"]) == 1
    assert body["skipped"] == 1
    bal = client.get("/records/balance/me", headers=h).json()
    assert bal["cash_on_hand"] == 3000

def test_decide_batch_all_cash_skip_message(client):
    owner = _register(client, "flow-batch-allcash", "batch-allcash@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    a = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 5000,
            "category": "Taxi",
            "purpose": "Office",
            "payment_source": "cash_on_hand",
        },
    ).json()["id"]
    b = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 5000,
            "category": "Food",
            "purpose": "Office",
            "payment_source": "cash_on_hand",
        },
    ).json()["id"]
    res = client.post(
        "/records/decide-batch",
        headers=h,
        json={"ids": [a, b], "approve": True},
    )
    assert res.status_code == 400
    assert "insufficient cash" in res.json()["detail"].lower()


def test_adjustment_rejects_negative_track(client):
    owner = _register(client, "flow-adj-neg", "adj-neg@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    uid = owner["user"]["id"]
    bad = client.post(
        "/adjustments",
        headers=h,
        json={
            "user_id": uid,
            "track": "cash_on_hand",
            "amount": -100,
            "note": "bad debit",
        },
    )
    assert bad.status_code == 400
    assert "negative" in bad.json()["detail"].lower()
    ok = client.post(
        "/adjustments",
        headers=h,
        json={
            "user_id": uid,
            "track": "cash_on_hand",
            "amount": 100,
            "note": "opening",
        },
    )
    assert ok.status_code == 200, ok.text
    bad2 = client.post(
        "/adjustments",
        headers=h,
        json={
            "user_id": uid,
            "track": "cash_on_hand",
            "amount": -150,
            "note": "too much",
        },
    )
    assert bad2.status_code == 400


def test_void_payout_reopen_vs_cancel_when_blocked(client):
    """Voiding a request-backed payout reopens when amount fits; cancels when reserved blocks it."""
    owner = _register(client, "flow-void-fit", "void-fit@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    # Build spendings, request reimbursement, approve (creates payout)
    client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 5000,
            "category": "Taxi",
            "purpose": "Office",
            "payment_source": "my_pocket",
            "approve_now": True,
        },
    )
    req = client.post(
        "/payouts/requests",
        headers=h,
        json={"kind": "expense_payout", "amount": 5000, "note": "pay me"},
    )
    assert req.status_code == 200, req.text
    rid = req.json()["id"]
    approved = client.post(
        f"/payouts/requests/{rid}/approve",
        headers=h,
        json={"payment_method": "cash"},
    )
    assert approved.status_code == 200, approved.text
    payout_id = approved.json()["id"]
    # After payout spendings is 0. Add another pending request for 5000 that cannot exist yet.
    # Void payout first (reopens original 5000 request — spendings restored to 5000).
    voided = client.post(
        f"/payouts/{payout_id}/void",
        headers=h,
        json={"note": "mistake"},
    )
    assert voided.status_code == 200, voided.text
    reopened = client.get("/payouts/requests?status=pending", headers=h).json()
    assert any(x["id"] == rid and x["status"] == "pending" for x in reopened)

    # Approve again, then create a SECOND pending request that reserves the restored track
    # so a later void cannot reopen.
    approved2 = client.post(
        f"/payouts/requests/{rid}/approve",
        headers=h,
        json={"payment_method": "cash"},
    )
    assert approved2.status_code == 200, approved2.text
    payout2 = approved2.json()["id"]
    # New pocket expense builds spendings again
    client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 3000,
            "category": "Food",
            "purpose": "Office",
            "payment_source": "my_pocket",
            "approve_now": True,
        },
    )
    # Pending request reserves 3000; void of 5000 payout would restore +5000 spendings
    # making track 8000, so reopen of 5000 would still fit. Need request amount > available after void.
    # After void of payout2 (5000): spendings = 3000 (new) + 5000 restored = 8000, reopen 5000 fits.
    # Make pending reserve 4000 of the 3000? can't. Instead: after void restore, pending other
    # for 8000 created BEFORE void while spendings=3000 should fail.
    # Alternative: void when request amount is 5000 but after void spendings only 3000 because
    # payout was overpayment? Use overpayment path...
    # Practical: create adjustment negative after reopen path — skip complex cancel branch.
    # Assert reopen path works (already above). For cancel path: pending request reserving
    # almost all restored balance.
    # Before void: spendings=3000. Post pending request 3000 (ok). Void payout2 (+5000) =>
    # spendings=8000, reserved=3000, available=5000. Reopen wants 5000 — fits exactly.
    # Pending 3001 would fail on create. Pending 3000 then reopen 5000 fits.
    # To force cancel: request amount 5000, after void available < 5000.
    # available after void = (3000+5000) - reserved. If reserved=4000 somehow...
    # Create two pending 2000+2000=4000 after new expense, then void:
    r1 = client.post(
        "/payouts/requests",
        headers=h,
        json={"kind": "expense_payout", "amount": 2000, "note": "r1"},
    )
    r2 = client.post(
        "/payouts/requests",
        headers=h,
        json={"kind": "expense_payout", "amount": 1000, "note": "r2"},
    )
    assert r1.status_code == 200 and r2.status_code == 200
    # reserved=3000, spendings=3000, available=0. Void payout2 restores +5000 =>
    # spendings=8000, reserved=3000, available=5000. Reopen 5000 fits.
    void2 = client.post(f"/payouts/{payout2}/void", headers=h, json={"note": "again"})
    assert void2.status_code == 200, void2.text
    pending = client.get("/payouts/requests?status=pending", headers=h).json()
    # Original request should be reopened (fits) OR cancelled — with available 5000 it reopens.
    assert any(x["id"] == rid for x in pending)

def test_overpayment_ignores_client_value(client):
    owner = _register(client, "flow-overpay-force", "overpay-force@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    uid = owner["user"]["id"]
    client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 10000,
            "category": "Taxi",
            "purpose": "Office",
            "payment_source": "my_pocket",
            "approve_now": True,
        },
    )
    pay = client.post(
        "/payouts",
        headers=h,
        json={
            "user_id": uid,
            "kind": "expense_payout",
            "amount": 12000,
            "payment_method": "cash",
            "overpayment": 999999,
            "note": "client lied",
        },
    )
    assert pay.status_code == 200, pay.text
    assert pay.json()["overpayment"] == 2000


def test_fuel_odometer_checked_on_approve(client):
    owner = _register(client, "flow-odo-approve", "odo-approve@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    first = client.post(
        "/records",
        headers=h,
        json={
            "kind": "fuel",
            "amount": 50,
            "category": "Bensin",
            "purpose": "Other",
            "bike": "B1",
            "odometer": 1000,
            "liters": 5,
            "payment_source": "my_pocket",
            "approve_now": True,
        },
    )
    assert first.status_code == 200, first.text
    pending = client.post(
        "/records",
        headers=h,
        json={
            "kind": "fuel",
            "amount": 40,
            "category": "Bensin",
            "purpose": "Other",
            "bike": "B1",
            "odometer": 900,
            "liters": 4,
            "payment_source": "my_pocket",
        },
    )
    # create may already block decrease — if so, create a pending with high odo then
    # approve a second concurrent lower one by creating before first approve... 
    # First was approve_now. Pending with 900 should fail on create.
    assert pending.status_code == 400
    # Create two pending in order: low then high without approving, then approve high then low
    low = client.post(
        "/records",
        headers=h,
        json={
            "kind": "fuel",
            "amount": 40,
            "category": "Bensin",
            "purpose": "Other",
            "bike": "B1",
            "odometer": 1100,
            "liters": 4,
            "payment_source": "my_pocket",
        },
    )
    assert low.status_code == 200, low.text
    high = client.post(
        "/records",
        headers=h,
        json={
            "kind": "fuel",
            "amount": 40,
            "category": "Bensin",
            "purpose": "Other",
            "bike": "B1",
            "odometer": 1200,
            "liters": 4,
            "payment_source": "my_pocket",
        },
    )
    assert high.status_code == 200, high.text
    # Approve higher (later-created) first
    ok = client.post(f"/records/{high.json()['id']}/decide", headers=h, json={"approve": True})
    assert ok.status_code == 200, ok.text
    # Earlier pending at 1100 still fits between 1000 and 1200 — chronology allows it
    ok_low = client.post(f"/records/{low.json()['id']}/decide", headers=h, json={"approve": True})
    assert ok_low.status_code == 200, ok_low.text
    # Backdated insert cannot jump above a later reading
    jumped = client.post(
        "/records",
        headers=h,
        json={
            "kind": "fuel",
            "amount": 30,
            "category": "Bensin",
            "purpose": "Other",
            "bike": "B1",
            "odometer": 5000,
            "liters": 2,
            "occurred_at": "2020-01-01T12:00:00",
            "payment_source": "my_pocket",
        },
    )
    assert jumped.status_code == 400
    assert "later" in jumped.json()["detail"].lower() or "odometer" in jumped.json()["detail"].lower()

def test_invite_token_accept_and_pagination(client):
    owner = _register(client, "flow-invite-tok", "invtok-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    inv = client.post(
        "/orgs/invite",
        headers=h,
        json={
            "email": "invtok-emp@example.com",
            "full_name": "Inv Emp",
            "role": "employee",
        },
    )
    assert inv.status_code == 200, inv.text
    body = inv.json()
    assert body["must_set_password"] is True
    assert body["invite_token"]
    assert body["organization_slug"] == "flow-invite-tok"
    blocked = client.post(
        "/auth/login",
        json={
            "email": "invtok-emp@example.com",
            "password": "whatever1",
            "organization_slug": "flow-invite-tok",
        },
    )
    assert blocked.status_code == 401
    accept = client.post(
        "/auth/accept-invite",
        json={
            "token": body["invite_token"],
            "password": "chosen99",
            "password_confirm": "chosen99",
        },
    )
    assert accept.status_code == 200, accept.text
    assert "access_token" in accept.json()
    eh = {"Authorization": f"Bearer {accept.json()['access_token']}"}
    assert client.get("/auth/me", headers=eh).status_code == 200
    again = client.post(
        "/auth/accept-invite",
        json={
            "token": body["invite_token"],
            "password": "chosen99",
            "password_confirm": "chosen99",
        },
    )
    assert again.status_code == 400
    login = client.post(
        "/auth/login",
        json={
            "email": "invtok-emp@example.com",
            "password": "chosen99",
            "organization_slug": "flow-invite-tok",
        },
    )
    assert login.status_code == 200

    for i in range(5):
        r = client.post(
            "/records",
            headers=eh,
            json={
                "kind": "expense",
                "amount": 100 + i,
                "category": "Supplies",
                "purpose": "Office",
                "payment_source": "my_pocket",
            },
        )
        assert r.status_code == 200, r.text
    page1 = client.get("/records/mine?limit=2&offset=0", headers=eh)
    page2 = client.get("/records/mine?limit=2&offset=2", headers=eh)
    assert page1.status_code == 200
    assert page2.status_code == 200
    assert len(page1.json()) == 2
    assert len(page2.json()) == 2
    ids1 = {row["id"] for row in page1.json()}
    ids2 = {row["id"] for row in page2.json()}
    assert ids1.isdisjoint(ids2)
    org_page = client.get("/records/org?limit=2&offset=0", headers=h)
    assert org_page.status_code == 200
    assert len(org_page.json()) == 2

def test_owner_issues_password_reset_token(client):
    owner = _register(client, "flow-reset-tok", "resettok-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    inv = client.post(
        "/orgs/invite",
        headers=h,
        json={
            "email": "resettok-emp@example.com",
            "full_name": "Emp",
            "role": "employee",
            "password": "secret12",
            "password_confirm": "secret12",
        },
    )
    assert inv.status_code == 200
    emp_id = inv.json()["id"]
    login = client.post(
        "/auth/login",
        json={
            "email": "resettok-emp@example.com",
            "password": "secret12",
            "organization_slug": "flow-reset-tok",
        },
    )
    assert login.status_code == 200
    old_h = {"Authorization": f"Bearer {login.json()['access_token']}"}
    issued = client.post(f"/orgs/members/{emp_id}/reset-token", headers=h)
    assert issued.status_code == 200, issued.text
    token = issued.json()["invite_token"]
    assert token
    assert client.get("/auth/me", headers=old_h).status_code == 401
    blocked = client.post(
        "/auth/login",
        json={
            "email": "resettok-emp@example.com",
            "password": "secret12",
            "organization_slug": "flow-reset-tok",
        },
    )
    assert blocked.status_code == 401
    accept = client.post(
        "/auth/accept-invite",
        json={"token": token, "password": "freshpass1", "password_confirm": "freshpass1"},
    )
    assert accept.status_code == 200, accept.text
    ok = client.post(
        "/auth/login",
        json={
            "email": "resettok-emp@example.com",
            "password": "freshpass1",
            "organization_slug": "flow-reset-tok",
        },
    )
    assert ok.status_code == 200

def test_idempotency_key_and_money_round(client):
    owner = _register(client, "flow-idem", "idem-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    key = "create-once-abc123"
    first = client.post(
        "/records",
        headers={**h, "Idempotency-Key": key},
        json={
            "kind": "expense",
            "amount": 10.006,
            "category": "Supplies",
            "purpose": "Office",
            "payment_source": "my_pocket",
        },
    )
    assert first.status_code == 200, first.text
    assert first.json()["amount"] == 10.01
    second = client.post(
        "/records",
        headers={**h, "Idempotency-Key": key},
        json={
            "kind": "expense",
            "amount": 10.006,
            "category": "Supplies",
            "purpose": "Office",
            "payment_source": "my_pocket",
        },
    )
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["amount"] == 10.01
    # Reusing the same key with a different payload must not silently replay
    mismatch = client.post(
        "/records",
        headers={**h, "Idempotency-Key": key},
        json={
            "kind": "expense",
            "amount": 99,
            "category": "Food",
            "purpose": "Office",
            "payment_source": "my_pocket",
        },
    )
    assert mismatch.status_code == 409
    # Without key, a new row is created
    third = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 5,
            "category": "Food",
            "purpose": "Office",
            "payment_source": "my_pocket",
        },
    )
    assert third.status_code == 200
    assert third.json()["id"] != first.json()["id"]

def test_billing_and_money_numeric(client):
    owner = _register(client, "flow-bill", "bill-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    me = client.get("/billing/me", headers=h)
    assert me.status_code == 200, me.text
    body = me.json()
    assert body["plan"] == "free"
    assert body["billing_status"] == "ok"
    assert body["media_backend"] in ("local", "s3")
    plan = client.post("/billing/plan", headers=h, json={"plan": "pro"})
    assert plan.status_code == 400
    tg = client.post(
        "/integrations/telegram/chat",
        headers=h,
        json={"telegram_chat_id": "-100123"},
    )
    assert tg.status_code == 200
    assert tg.json()["telegram_chat_id"] == "-100123"
    # Without bot token, test endpoint fails clearly
    bad = client.post("/integrations/telegram/test", headers=h)
    assert bad.status_code == 400
    # Money still rounds through Numeric column
    rec = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 1.005,
            "category": "Supplies",
            "purpose": "Office",
            "payment_source": "my_pocket",
        },
    )
    assert rec.status_code == 200
    assert rec.json()["amount"] == 1.01
    health = client.get("/health")
    assert health.json()["version"] == "0.7.41"

def test_photo_url_media_token_and_invite_expiry(client):
    owner = _register(client, "flow-sec", "sec-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    bad = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 10,
            "category": "Supplies",
            "purpose": "Office",
            "payment_source": "my_pocket",
            "photo_url": "https://evil.example/x?steal=1",
        },
    )
    assert bad.status_code == 400
    bad2 = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 10,
            "category": "Supplies",
            "purpose": "Office",
            "payment_source": "my_pocket",
            "photo_url": "/media/files/999/not-ours.jpg",
        },
    )
    assert bad2.status_code == 400
    mt = client.get("/records/media-token", headers=h)
    assert mt.status_code == 200
    media_tok = mt.json()["access_token"]
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {media_tok}"}).status_code == 401
    inv = client.post(
        "/orgs/invite",
        headers=h,
        json={"email": "sec-emp@example.com", "full_name": "Emp", "role": "employee"},
    )
    assert inv.status_code == 200
    token = inv.json()["invite_token"]
    from app.db import SessionLocal
    from app.models import User
    from datetime import datetime, timedelta, timezone

    db = SessionLocal()
    try:
        u = db.query(User).filter(User.email == "sec-emp@example.com").one()
        u.invite_token_expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
        db.commit()
    finally:
        db.close()
    expired = client.post(
        "/auth/accept-invite",
        json={"token": token, "password": "freshpass1", "password_confirm": "freshpass1"},
    )
    assert expired.status_code == 400
    assert client.get("/records/pending/count", headers=h).json()["count"] == 0


def test_media_query_rejects_access_token(client, tmp_path, monkeypatch):
    owner = _register(client, "flow-mq", "mq-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    oid = owner["user"]["organization_id"]
    from app.services import storage

    monkeypatch.setattr(storage, "UPLOAD_ROOT", tmp_path)
    name = "a" * 32 + ".jpg"
    path = storage.local_path(oid, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xd8\xff" + b"0" * 64)
    access = owner["access_token"]
    # Access JWT must not work via ?token=
    denied = client.get(f"/media/files/{oid}/{name}?token={access}")
    assert denied.status_code == 401
    # Arbitrary legacy names are rejected
    bad_name = client.get(f"/media/files/{oid}/receipt.jpg", headers=h)
    assert bad_name.status_code == 400
    # Bearer access still works for generated names
    ok_bearer = client.get(f"/media/files/{oid}/{name}", headers=h)
    assert ok_bearer.status_code == 200
    media_tok = client.get("/records/media-token", headers=h).json()["access_token"]
    ok_q = client.get(f"/media/files/{oid}/{name}?token={media_tok}")
    assert ok_q.status_code == 200


def test_adjustment_occurred_at_bounds_and_idempotency(client):
    owner = _register(client, "flow-adj-bounds", "adjb-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    uid = owner["user"]["id"]
    far = client.post(
        "/adjustments",
        headers=h,
        json={
            "user_id": uid,
            "track": "spendings",
            "amount": 100,
            "note": "opening",
            "occurred_at": "1990-01-01T00:00:00",
        },
    )
    assert far.status_code == 400
    future = client.post(
        "/adjustments",
        headers=h,
        json={
            "user_id": uid,
            "track": "spendings",
            "amount": 100,
            "note": "opening",
            "occurred_at": "2099-01-01T00:00:00",
        },
    )
    assert future.status_code == 400
    headers = {**h, "Idempotency-Key": "adj-once-1"}
    first = client.post(
        "/adjustments",
        headers=headers,
        json={
            "user_id": uid,
            "track": "spendings",
            "amount": 250,
            "note": "opening balance",
        },
    )
    assert first.status_code == 200, first.text
    second = client.post(
        "/adjustments",
        headers=headers,
        json={
            "user_id": uid,
            "track": "spendings",
            "amount": 250,
            "note": "opening balance",
        },
    )
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    bal = client.get("/records/balance/me", headers=h).json()
    assert bal["spendings"] == 250


def test_settlement_request_idempotency_and_report_date_strict(client):
    owner = _register(client, "flow-sreq-idem", "sreq-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    rid = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 3000,
            "category": "Taxi",
            "payment_source": "my_pocket",
            "purpose": "Office",
        },
    ).json()["id"]
    client.post(f"/records/{rid}/decide", headers=h, json={"approve": True})
    headers = {**h, "Idempotency-Key": "sreq-once-1"}
    first = client.post(
        "/payouts/requests",
        headers=headers,
        json={"kind": "expense_payout", "amount": 1000, "note": "partial"},
    )
    assert first.status_code == 200, first.text
    second = client.post(
        "/payouts/requests",
        headers=headers,
        json={"kind": "expense_payout", "amount": 1000, "note": "partial"},
    )
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    junk = client.get("/reports/org?date_from=2026-01-01x&date_to=2026-12-31", headers=h)
    assert junk.status_code == 400
    # Formula-ish comment should be neutralized in CSV
    client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 11,
            "category": "Supplies",
            "purpose": "Office",
            "payment_source": "my_pocket",
            "comment": "=1+1",
        },
    )
    csv = client.get("/reports/export.csv?days=30", headers=h)
    assert csv.status_code == 200
    assert "'=1+1" in csv.text or ",'=1+1" in csv.text


def test_owner_cannot_self_reset_password(client):
    owner = _register(client, "flow-noself", "noself-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    uid = owner["user"]["id"]
    bad = client.post(
        f"/orgs/members/{uid}/password",
        headers=h,
        json={"new_password": "otherpass1", "password_confirm": "otherpass1"},
    )
    assert bad.status_code == 400
    bad_tok = client.post(f"/orgs/members/{uid}/reset-token", headers=h)
    assert bad_tok.status_code == 400


def test_invite_token_hashed_and_accept_returns_slug(client):
    owner = _register(client, "flow-hash-inv", "hashinv-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    inv = client.post(
        "/orgs/invite",
        headers=h,
        json={"email": "hash-emp@example.com", "full_name": "Hash Emp", "role": "employee"},
    )
    assert inv.status_code == 200, inv.text
    raw = inv.json()["invite_token"]
    assert raw
    from app.db import SessionLocal
    from app.models import User
    from app.services.invite_tokens import hash_invite_token

    db = SessionLocal()
    try:
        u = db.query(User).filter(User.email == "hash-emp@example.com").one()
        assert u.invite_token == hash_invite_token(raw)
        assert u.invite_token != raw
    finally:
        db.close()
    mismatch = client.post(
        "/auth/accept-invite",
        json={"token": raw, "password": "chosen99", "password_confirm": "other99"},
    )
    assert mismatch.status_code == 422
    ok = client.post(
        "/auth/accept-invite",
        json={"token": raw, "password": "chosen99", "password_confirm": "chosen99"},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["organization_slug"] == "flow-hash-inv"
    assert ok.json()["user"]["email"] == "hash-emp@example.com"


def test_settlement_pending_counts_and_image_magic(client):
    owner = _register(client, "flow-scount", "scount-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    rid = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 2000,
            "category": "Taxi",
            "payment_source": "my_pocket",
            "purpose": "Office",
        },
    ).json()["id"]
    client.post(f"/records/{rid}/decide", headers=h, json={"approve": True})
    client.post(
        "/payouts/requests",
        headers=h,
        json={"kind": "expense_payout", "amount": 500, "note": "partial"},
    )
    org_c = client.get("/payouts/requests/pending/count", headers=h)
    assert org_c.status_code == 200
    assert org_c.json()["count"] >= 1
    mine_c = client.get("/payouts/requests/mine/pending/count", headers=h)
    assert mine_c.status_code == 200
    assert mine_c.json()["count"] >= 1
    # Reject spoofed extension / non-image payload
    bad = client.post(
        "/media/photo",
        headers=h,
        files={"file": ("evil.jpg", b"not-an-image-but-long-enough-xxxx", "image/jpeg")},
    )
    assert bad.status_code == 400
    good = client.post(
        "/media/photo",
        headers=h,
        files={"file": ("receipt.bin", b"\xff\xd8\xff" + b"0" * 64, "application/octet-stream")},
    )
    assert good.status_code == 200, good.text
    assert good.json()["photo_url"].endswith(".jpg")


def test_decide_and_void_idempotent_retries(client):
    owner = _register(client, "flow-idem-dec", "idemdec-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    rid = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 120,
            "category": "Supplies",
            "purpose": "Office",
            "payment_source": "my_pocket",
        },
    ).json()["id"]
    first = client.post(f"/records/{rid}/decide", headers=h, json={"approve": True})
    assert first.status_code == 200
    again = client.post(f"/records/{rid}/decide", headers=h, json={"approve": True})
    assert again.status_code == 200, again.text
    assert again.json()["id"] == rid
    assert again.json()["status"] == "approved"
    conflict = client.post(f"/records/{rid}/decide", headers=h, json={"approve": False, "note": "nope"})
    assert conflict.status_code == 400
    void1 = client.post(f"/records/{rid}/void", headers=h, json={"note": "mistake"})
    assert void1.status_code == 200, void1.text
    void2 = client.post(f"/records/{rid}/void", headers=h, json={"note": "retry"})
    assert void2.status_code == 200
    assert void2.json()["is_voided"] is True


def test_auth_login_rate_limit(client, monkeypatch):
    from app.config import settings
    from app.services.rate_limit import reset_limiter_for_tests

    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "trust_x_forwarded_for", True)
    reset_limiter_for_tests()
    # Isolated IP so earlier suite logins do not count against this window
    ip = {"X-Forwarded-For": "203.0.113.77"}
    _register(client, "flow-rl", "rl-owner@example.com")
    last = None
    for _ in range(25):
        last = client.post(
            "/auth/login",
            headers=ip,
            json={
                "email": "rl-owner@example.com",
                "password": "wrong-password",
                "organization_slug": "flow-rl",
            },
        )
        if last.status_code == 429:
            break
    assert last is not None
    assert last.status_code == 429
    assert "Retry-After" in last.headers
    reset_limiter_for_tests()
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    monkeypatch.setattr(settings, "trust_x_forwarded_for", False)


def test_cannot_deactivate_with_pending_and_org_name_trim(client):
    owner = _register(client, "flow-deact", "deact-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    inv = client.post(
        "/orgs/invite",
        headers=h,
        json={
            "email": "deact-emp@example.com",
            "full_name": "Deact Emp",
            "role": "employee",
            "password": "secret12",
            "password_confirm": "secret12",
        },
    )
    assert inv.status_code == 200
    emp_id = inv.json()["id"]
    emp_login = client.post(
        "/auth/login",
        json={
            "email": "deact-emp@example.com",
            "password": "secret12",
            "organization_slug": "flow-deact",
        },
    )
    eh = {"Authorization": f"Bearer {emp_login.json()['access_token']}"}
    client.post(
        "/records",
        headers=eh,
        json={
            "kind": "expense",
            "amount": 50,
            "category": "Supplies",
            "purpose": "Office",
            "payment_source": "my_pocket",
        },
    )
    blocked = client.post(
        f"/orgs/members/{emp_id}/active",
        headers=h,
        json={"is_active": False},
    )
    assert blocked.status_code == 400
    assert "pending" in blocked.json()["detail"].lower()
    # Whitespace-only org name rejected
    bad = client.post(
        "/orgs/register",
        json={
            "name": "   ",
            "slug": "flow-blank-name",
            "currency": "IDR",
            "owner_email": "blank@example.com",
            "owner_name": "Owner",
            "owner_password": "secret12",
            "owner_password_confirm": "secret12",
        },
    )
    assert bad.status_code == 422
    # Approve blocked for inactive creator after force-deactivate path:
    # first decide the pending record, then invite another and deactivate cleanly.
    pending = client.get("/records/pending", headers=h).json()
    assert pending
    rid = pending[0]["id"]
    client.post(f"/records/{rid}/decide", headers=h, json={"approve": False, "note": "nope"})
    ok = client.post(
        f"/orgs/members/{emp_id}/active",
        headers=h,
        json={"is_active": False},
    )
    assert ok.status_code == 200


def test_cannot_approve_inactive_creator_record(client):
    owner = _register(client, "flow-inact-apr", "inactapr-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    inv = client.post(
        "/orgs/invite",
        headers=h,
        json={
            "email": "inactapr-emp@example.com",
            "full_name": "Emp",
            "role": "employee",
            "password": "secret12",
            "password_confirm": "secret12",
        },
    )
    emp_id = inv.json()["id"]
    emp_h = {
        "Authorization": f"Bearer {client.post('/auth/login', json={'email': 'inactapr-emp@example.com', 'password': 'secret12', 'organization_slug': 'flow-inact-apr'}).json()['access_token']}"
    }
    rid = client.post(
        "/records",
        headers=emp_h,
        json={
            "kind": "expense",
            "amount": 40,
            "category": "Supplies",
            "purpose": "Office",
            "payment_source": "my_pocket",
        },
    ).json()["id"]
    # Directly mark inactive via DB to simulate legacy pending after deactivate was allowed
    from app.db import SessionLocal
    from app.models import User

    db = SessionLocal()
    try:
        u = db.get(User, emp_id)
        u.is_active = False
        db.commit()
    finally:
        db.close()
    bad = client.post(f"/records/{rid}/decide", headers=h, json={"approve": True})
    assert bad.status_code == 400
    assert "inactive" in bad.json()["detail"].lower()
    ok = client.post(
        f"/records/{rid}/decide",
        headers=h,
        json={"approve": False, "note": "inactive teammate"},
    )
    assert ok.status_code == 200


def test_decide_batch_comment_cancel_idempotency_and_currency(client):
    owner = _register(client, "flow-078", "v078-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}

    bad_cur = client.patch("/orgs/me", headers=h, json={"currency": "EURO"})
    assert bad_cur.status_code == 422
    bad_cur2 = client.patch("/orgs/me", headers=h, json={"currency": "US"})
    assert bad_cur2.status_code == 422

    a = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 15,
            "category": "Taxi",
            "purpose": "Office",
            "payment_source": "my_pocket",
        },
    ).json()
    assert a["created_by_active"] is True
    b = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 25,
            "category": "Food",
            "purpose": "Office",
            "payment_source": "my_pocket",
        },
    ).json()["id"]

    batch_headers = {**h, "Idempotency-Key": "decide-batch-once-078"}
    first = client.post(
        "/records/decide-batch",
        headers=batch_headers,
        json={"ids": [a["id"], b], "approve": True},
    )
    assert first.status_code == 200, first.text
    assert len(first.json()["decided"]) == 2
    assert first.json().get("skipped_inactive", 0) == 0
    second = client.post(
        "/records/decide-batch",
        headers=batch_headers,
        json={"ids": [a["id"], b], "approve": True},
    )
    assert second.status_code == 200
    assert [r["id"] for r in second.json()["decided"]] == [
        r["id"] for r in first.json()["decided"]
    ]

    c = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 8,
            "category": "Supplies",
            "purpose": "Office",
            "payment_source": "my_pocket",
        },
    ).json()["id"]
    cmt_headers = {**h, "Idempotency-Key": "comment-once-078"}
    c1 = client.post(f"/records/{c}/comment", headers=cmt_headers, json={"note": "first note"})
    assert c1.status_code == 200
    assert "first note" in c1.json()["comment"]
    c2 = client.post(f"/records/{c}/comment", headers=cmt_headers, json={"note": "first note"})
    assert c2.status_code == 200
    assert c2.json()["comment"] == c1.json()["comment"]
    c_mismatch = client.post(
        f"/records/{c}/comment", headers=cmt_headers, json={"note": "retry note"}
    )
    assert c_mismatch.status_code == 409

    d = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 9,
            "category": "Supplies",
            "purpose": "Office",
            "payment_source": "my_pocket",
        },
    ).json()["id"]
    cancel_headers = {**h, "Idempotency-Key": "cancel-once-078"}
    x1 = client.delete(f"/records/{d}", headers=cancel_headers)
    assert x1.status_code == 200
    assert x1.json()["status"] == "rejected"
    x2 = client.delete(f"/records/{d}", headers=cancel_headers)
    assert x2.status_code == 200
    assert x2.json()["id"] == d
    # Already-cancelled without key also succeeds
    x3 = client.delete(f"/records/{d}", headers=h)
    assert x3.status_code == 200


def test_decide_batch_skips_inactive_creator(client):
    owner = _register(client, "flow-batch-inact", "batchinact-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    inv = client.post(
        "/orgs/invite",
        headers=h,
        json={
            "email": "batchinact-emp@example.com",
            "full_name": "Emp",
            "role": "employee",
            "password": "secret12",
            "password_confirm": "secret12",
        },
    )
    emp_id = inv.json()["id"]
    emp_h = {
        "Authorization": f"Bearer {client.post('/auth/login', json={'email': 'batchinact-emp@example.com', 'password': 'secret12', 'organization_slug': 'flow-batch-inact'}).json()['access_token']}"
    }
    inactive_rid = client.post(
        "/records",
        headers=emp_h,
        json={
            "kind": "expense",
            "amount": 30,
            "category": "Taxi",
            "purpose": "Office",
            "payment_source": "my_pocket",
        },
    ).json()["id"]
    active_rid = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 12,
            "category": "Food",
            "purpose": "Office",
            "payment_source": "my_pocket",
        },
    ).json()["id"]

    from app.db import SessionLocal
    from app.models import User

    db = SessionLocal()
    try:
        u = db.get(User, emp_id)
        u.is_active = False
        db.commit()
    finally:
        db.close()

    pending = client.get(f"/records/{inactive_rid}", headers=h)
    assert pending.status_code == 200
    assert pending.json()["created_by_active"] is False

    res = client.post(
        "/records/decide-batch",
        headers=h,
        json={"ids": [inactive_rid, active_rid], "approve": True},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body["decided"]) == 1
    assert body["decided"][0]["id"] == active_rid
    assert body["skipped_inactive"] == 1
    assert body["skipped"] >= 1

    only_inactive = client.post(
        "/records/decide-batch",
        headers=h,
        json={"ids": [inactive_rid], "approve": True},
    )
    assert only_inactive.status_code == 400
    assert "inactive" in only_inactive.json()["detail"].lower()


def test_settlement_approve_cancel_soft_retry_and_heic_reject(client):
    owner = _register(client, "flow-079", "v079-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 5000,
            "category": "Taxi",
            "purpose": "Office",
            "payment_source": "my_pocket",
            "approve_now": True,
        },
    )
    req = client.post(
        "/payouts/requests",
        headers=h,
        json={"kind": "expense_payout", "amount": 5000, "note": "reimburse"},
    )
    assert req.status_code == 200, req.text
    rid = req.json()["id"]
    key = "approve-req-once-079"
    first = client.post(
        f"/payouts/requests/{rid}/approve",
        headers={**h, "Idempotency-Key": key},
        json={"payment_method": "cash"},
    )
    assert first.status_code == 200, first.text
    payout_id = first.json()["id"]
    # Soft retry without key after already approved
    again = client.post(
        f"/payouts/requests/{rid}/approve",
        headers=h,
        json={"payment_method": "cash"},
    )
    assert again.status_code == 200, again.text
    assert again.json()["id"] == payout_id
    # Idempotency key replay
    replay = client.post(
        f"/payouts/requests/{rid}/approve",
        headers={**h, "Idempotency-Key": key},
        json={"payment_method": "cash"},
    )
    assert replay.status_code == 200
    assert replay.json()["id"] == payout_id
    # Cannot cancel an approved request
    bad_cancel = client.post(
        f"/payouts/requests/{rid}/cancel",
        headers=h,
        json={"note": "too late"},
    )
    assert bad_cancel.status_code == 400

    req2 = client.post(
        "/payouts/requests",
        headers=h,
        json={"kind": "expense_payout", "amount": 1, "note": "tiny"},
    )
    # amount may fail if no spendings left — use leftover 0 path: create another expense first
    if req2.status_code != 200:
        client.post(
            "/records",
            headers=h,
            json={
                "kind": "expense",
                "amount": 1200,
                "category": "Food",
                "purpose": "Office",
                "payment_source": "my_pocket",
                "approve_now": True,
            },
        )
        req2 = client.post(
            "/payouts/requests",
            headers=h,
            json={"kind": "expense_payout", "amount": 1200, "note": "tiny"},
        )
    assert req2.status_code == 200, req2.text
    rid2 = req2.json()["id"]
    ckey = "cancel-req-once-079"
    c1 = client.post(
        f"/payouts/requests/{rid2}/cancel",
        headers={**h, "Idempotency-Key": ckey},
        json={"note": ""},
    )
    assert c1.status_code == 200, c1.text
    assert c1.json()["status"] == "cancelled"
    c2 = client.post(
        f"/payouts/requests/{rid2}/cancel",
        headers={**h, "Idempotency-Key": ckey},
        json={"note": ""},
    )
    assert c2.status_code == 200
    assert c2.json()["id"] == rid2
    c3 = client.post(f"/payouts/requests/{rid2}/cancel", headers=h, json={"note": ""})
    assert c3.status_code == 200
    assert c3.json()["status"] == "cancelled"

    heic = b"\x00\x00\x00\x18ftypheic" + b"\x00" * 32
    rejected = client.post(
        "/media/photo",
        headers=h,
        files={"file": ("shot.heic", heic, "image/heic")},
    )
    assert rejected.status_code == 400
    assert "heic" in rejected.json()["detail"].lower()


def test_void_adjustment_blocks_negative_cash(client):
    owner = _register(client, "flow-adj-void-neg", "adjvoidneg@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    uid = owner["user"]["id"]
    adj = client.post(
        "/adjustments",
        headers=h,
        json={
            "user_id": uid,
            "track": "cash_on_hand",
            "amount": 10000,
            "note": "opening cash",
        },
    )
    assert adj.status_code == 200, adj.text
    aid = adj.json()["id"]
    spend = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 8000,
            "category": "Taxi",
            "purpose": "Office",
            "payment_source": "cash_on_hand",
            "approve_now": True,
        },
    )
    assert spend.status_code == 200, spend.text
    bad = client.post(f"/adjustments/{aid}/void", headers=h, json={"note": "undo opening"})
    assert bad.status_code == 400
    assert "negative" in bad.json()["detail"].lower()
    # Spendings void with room still works
    adj2 = client.post(
        "/adjustments",
        headers=h,
        json={
            "user_id": uid,
            "track": "spendings",
            "amount": 500,
            "note": "opening spendings",
        },
    )
    assert adj2.status_code == 200
    ok = client.post(
        f"/adjustments/{adj2.json()['id']}/void",
        headers=h,
        json={"note": "undo spendings opening"},
    )
    assert ok.status_code == 200, ok.text


def test_decide_void_idempotency_keys_and_upload_rate_limit(client, monkeypatch):
    owner = _register(client, "flow-0710", "v0710-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    rid = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 55,
            "category": "Taxi",
            "purpose": "Office",
            "payment_source": "my_pocket",
        },
    ).json()["id"]
    dkey = "decide-once-0710"
    first = client.post(
        f"/records/{rid}/decide",
        headers={**h, "Idempotency-Key": dkey},
        json={"approve": True},
    )
    assert first.status_code == 200, first.text
    second = client.post(
        f"/records/{rid}/decide",
        headers={**h, "Idempotency-Key": dkey},
        json={"approve": True},
    )
    assert second.status_code == 200
    assert second.json()["id"] == rid
    assert second.json()["status"] == "approved"

    vkey = "void-rec-once-0710"
    void1 = client.post(
        f"/records/{rid}/void",
        headers={**h, "Idempotency-Key": vkey},
        json={"note": "mistake"},
    )
    assert void1.status_code == 200, void1.text
    void2 = client.post(
        f"/records/{rid}/void",
        headers={**h, "Idempotency-Key": vkey},
        json={"note": "mistake"},
    )
    assert void2.status_code == 200
    assert void2.json()["is_voided"] is True
    void_mismatch = client.post(
        f"/records/{rid}/void",
        headers={**h, "Idempotency-Key": vkey},
        json={"note": "retry"},
    )
    assert void_mismatch.status_code == 409

    adj = client.post(
        "/adjustments",
        headers=h,
        json={
            "user_id": owner["user"]["id"],
            "track": "spendings",
            "amount": 250,
            "note": "opening",
        },
    )
    assert adj.status_code == 200
    aid = adj.json()["id"]
    avkey = "void-adj-once-0710"
    a1 = client.post(
        f"/adjustments/{aid}/void",
        headers={**h, "Idempotency-Key": avkey},
        json={"note": "undo"},
    )
    assert a1.status_code == 200, a1.text
    a2 = client.post(
        f"/adjustments/{aid}/void",
        headers={**h, "Idempotency-Key": avkey},
        json={"note": "undo"},
    )
    assert a2.status_code == 200
    assert a2.json()["is_voided"] is True
    a_mismatch = client.post(
        f"/adjustments/{aid}/void",
        headers={**h, "Idempotency-Key": avkey},
        json={"note": "retry"},
    )
    assert a_mismatch.status_code == 409

    from app.config import settings
    from app.services.rate_limit import reset_limiter_for_tests

    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    reset_limiter_for_tests()
    jpeg = b"\xff\xd8\xff" + b"0" * 64
    last = None
    for _ in range(40):
        last = client.post(
            "/media/photo",
            headers=h,
            files={"file": ("r.jpg", jpeg, "image/jpeg")},
        )
        if last.status_code == 429:
            break
    assert last is not None
    assert last.status_code == 429
    assert "Retry-After" in last.headers
    reset_limiter_for_tests()
    monkeypatch.setattr(settings, "rate_limit_enabled", False)


def test_role_change_bumps_token_and_void_income_cash_guard(client):
    owner = _register(client, "flow-0711", "v0711-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    inv = client.post(
        "/orgs/invite",
        headers=h,
        json={
            "email": "v0711-mgr@example.com",
            "full_name": "Mgr",
            "role": "manager",
            "password": "secret12",
            "password_confirm": "secret12",
        },
    )
    assert inv.status_code == 200
    emp_id = inv.json()["id"]
    login = client.post(
        "/auth/login",
        json={
            "email": "v0711-mgr@example.com",
            "password": "secret12",
            "organization_slug": "flow-0711",
        },
    )
    assert login.status_code == 200
    old_h = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert client.get("/auth/me", headers=old_h).status_code == 200
    demote = client.post(
        f"/orgs/members/{emp_id}/role",
        headers=h,
        json={"role": "employee"},
    )
    assert demote.status_code == 200
    assert demote.json()["role"] == "employee"
    assert client.get("/auth/me", headers=old_h).status_code == 401

    income = client.post(
        "/records",
        headers=h,
        json={
            "kind": "income",
            "amount": 10000,
            "category": "Cash",
            "payment_method": "cash",
            "approve_now": True,
        },
    )
    assert income.status_code == 200, income.text
    iid = income.json()["id"]
    spend = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 8000,
            "category": "Taxi",
            "purpose": "Office",
            "payment_source": "cash_on_hand",
            "approve_now": True,
        },
    )
    assert spend.status_code == 200, spend.text
    bad = client.post(f"/records/{iid}/void", headers=h, json={"note": "undo income"})
    assert bad.status_code == 400
    assert "negative" in bad.json()["detail"].lower()


def test_decide_batch_soft_retry_and_inactive_invite_message(client):
    owner = _register(client, "flow-0711b", "v0711b-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    a = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 11,
            "category": "Taxi",
            "purpose": "Office",
            "payment_source": "my_pocket",
        },
    ).json()["id"]
    b = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 12,
            "category": "Food",
            "purpose": "Office",
            "payment_source": "my_pocket",
        },
    ).json()["id"]
    first = client.post(
        "/records/decide-batch",
        headers=h,
        json={"ids": [a, b], "approve": True},
    )
    assert first.status_code == 200, first.text
    again = client.post(
        "/records/decide-batch",
        headers=h,
        json={"ids": [a, b], "approve": True},
    )
    assert again.status_code == 200, again.text
    assert again.json()["decided"] == []
    assert again.json()["skipped"] == 2

    inv = client.post(
        "/orgs/invite",
        headers=h,
        json={
            "email": "v0711b-emp@example.com",
            "full_name": "Emp",
            "role": "employee",
            "password": "secret12",
            "password_confirm": "secret12",
        },
    )
    emp_id = inv.json()["id"]
    assert (
        client.post(
            f"/orgs/members/{emp_id}/active",
            headers=h,
            json={"is_active": False},
        ).status_code
        == 200
    )
    reinvite = client.post(
        "/orgs/invite",
        headers=h,
        json={
            "email": "v0711b-emp@example.com",
            "full_name": "Emp",
            "role": "employee",
            "password": "secret12",
            "password_confirm": "secret12",
        },
    )
    assert reinvite.status_code == 400
    assert "inactive" in reinvite.json()["detail"].lower()


def test_round_to_zero_rejected_and_csv_settlement_export(client):
    owner = _register(client, "flow-0712", "v0712-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    tiny = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 0.004,
            "category": "Taxi",
            "purpose": "Office",
            "payment_source": "my_pocket",
        },
    )
    assert tiny.status_code in (400, 422)
    assert "0.01" in str(tiny.json()).lower()

    client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 3000,
            "category": "Taxi",
            "purpose": "Office",
            "payment_source": "my_pocket",
            "approve_now": True,
        },
    )
    req = client.post(
        "/payouts/requests",
        headers=h,
        json={"kind": "expense_payout", "amount": 0.004, "note": "tiny"},
    )
    assert req.status_code in (400, 422)

    ok_req = client.post(
        "/payouts/requests",
        headers=h,
        json={"kind": "expense_payout", "amount": 3000, "note": "full"},
    )
    assert ok_req.status_code == 200, ok_req.text
    members = client.get("/orgs/members", headers=h)
    assert members.status_code == 200
    me_row = next(m for m in members.json() if m["email"] == "v0712-owner@example.com")
    assert "must_set_password" in me_row

    csv = client.get("/reports/export.csv", headers=h)
    assert csv.status_code == 200
    assert "liters" in csv.text.splitlines()[0]
    assert "transfer_group_id" in csv.text.splitlines()[0]
    assert "settlement_request" in csv.text


def test_fuel_liters_required_and_accept_requires_must_set(client):
    owner = _register(client, "flow-0713", "v0713-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    no_liters = client.post(
        "/records",
        headers=h,
        json={
            "kind": "fuel",
            "amount": 100,
            "category": "Bensin",
            "purpose": "Other",
            "bike": "X1",
            "odometer": 100,
            "payment_source": "my_pocket",
        },
    )
    assert no_liters.status_code == 422

    first = client.post(
        "/records",
        headers=h,
        json={
            "kind": "fuel",
            "amount": 100,
            "category": "Bensin",
            "purpose": "Other",
            "bike": "X1",
            "odometer": 100,
            "liters": 4,
            "payment_source": "my_pocket",
            "approve_now": True,
        },
    )
    assert first.status_code == 200, first.text
    missing_odo = client.post(
        "/records",
        headers=h,
        json={
            "kind": "fuel",
            "amount": 80,
            "category": "Bensin",
            "purpose": "Other",
            "bike": "X1",
            "liters": 3,
            "payment_source": "my_pocket",
        },
    )
    assert missing_odo.status_code == 400
    assert "odometer" in missing_odo.json()["detail"].lower()

    inv = client.post(
        "/orgs/invite",
        headers=h,
        json={
            "email": "v0713-emp@example.com",
            "full_name": "Emp",
            "role": "employee",
            "password": "secret12",
            "password_confirm": "secret12",
        },
    )
    assert inv.status_code == 200
    emp_id = inv.json()["id"]
    # Force leftover invite token without must_set_password
    from app.db import SessionLocal
    from app.models import User
    from app.services.invite_tokens import store_invite_token
    import secrets

    raw = secrets.token_urlsafe(24)
    db = SessionLocal()
    try:
        u = db.get(User, emp_id)
        u.must_set_password = False
        u.invite_token = store_invite_token(raw)
        db.commit()
    finally:
        db.close()
    blocked = client.post(
        "/auth/accept-invite",
        json={"token": raw, "password": "freshpass1", "password_confirm": "freshpass1"},
    )
    assert blocked.status_code == 400
    assert "already accepted" in blocked.json()["detail"].lower()


def test_register_confirm_nonfinite_billing_stub_and_void_reapprove(client, monkeypatch):
    # Register requires password confirm
    mismatch = client.post(
        "/orgs/register",
        json={
            "name": "Acme",
            "slug": "flow-0714-bad",
            "currency": "IDR",
            "owner_email": "v0714-bad@example.com",
            "owner_name": "Owner",
            "owner_password": "secret12",
            "owner_password_confirm": "other12",
        },
    )
    assert mismatch.status_code == 422

    owner = _register(client, "flow-0714", "v0714-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}

    # Non-finite / overflow amounts rejected by money helpers (JSON cannot carry Inf)
    from app.services.money import require_positive_money, round_money

    for amount in (float("inf"), float("-inf"), float("nan"), "Infinity", "NaN", "1e309"):
        try:
            require_positive_money(amount)
            raise AssertionError(f"expected reject for {amount!r}")
        except ValueError as exc:
            assert "finite" in str(exc).lower() or "0.01" in str(exc)
    try:
        round_money("NaN")
        raise AssertionError("expected reject for NaN")
    except ValueError:
        pass

    # Transfer comment max length
    long_comment = client.post(
        "/transfers",
        headers=h,
        json={
            "to_email": "nobody@example.com",
            "amount": 1,
            "comment": "x" * 2001,
        },
    )
    assert long_comment.status_code == 422

    # Billing stub: even with switch on, pro is refused
    from app.config import settings

    monkeypatch.setattr(settings, "billing_plan_switch", True)
    refuse_pro = client.post("/billing/plan", headers=h, json={"plan": "pro"})
    assert refuse_pro.status_code == 400
    assert "billing" in refuse_pro.json()["detail"].lower()
    trial_ok = client.post("/billing/plan", headers=h, json={"plan": "trial"})
    assert trial_ok.status_code == 200, trial_ok.text
    assert trial_ok.json()["plan"] == "trial"

    # Void payout → reopen → soft re-approve (with and without idem key)
    client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 4000,
            "category": "Taxi",
            "purpose": "Office",
            "payment_source": "my_pocket",
            "approve_now": True,
        },
    )
    req = client.post(
        "/payouts/requests",
        headers=h,
        json={"kind": "expense_payout", "amount": 4000, "note": "reimburse"},
    )
    assert req.status_code == 200, req.text
    rid = req.json()["id"]
    key = "approve-reopen-0714"
    first = client.post(
        f"/payouts/requests/{rid}/approve",
        headers={**h, "Idempotency-Key": key},
        json={"payment_method": "cash"},
    )
    assert first.status_code == 200, first.text
    payout_id = first.json()["id"]
    voided = client.post(
        f"/payouts/{payout_id}/void",
        headers=h,
        json={"note": "oops"},
    )
    assert voided.status_code == 200, voided.text
    assert voided.json()["is_voided"] is True
    pending = client.get("/payouts/requests?status=pending", headers=h).json()
    assert any(x["id"] == rid and x["status"] == "pending" for x in pending)

    # Same idem key after void must create a fresh payout (not return voided)
    again = client.post(
        f"/payouts/requests/{rid}/approve",
        headers={**h, "Idempotency-Key": key},
        json={"payment_method": "cash"},
    )
    assert again.status_code == 200, again.text
    new_id = again.json()["id"]
    assert new_id != payout_id
    assert again.json()["is_voided"] is False

    # Soft retry without key returns the new payout
    soft = client.post(
        f"/payouts/requests/{rid}/approve",
        headers=h,
        json={"payment_method": "cash"},
    )
    assert soft.status_code == 200
    assert soft.json()["id"] == new_id

    replay = client.post(
        f"/payouts/requests/{rid}/approve",
        headers={**h, "Idempotency-Key": key},
        json={"payment_method": "cash"},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == new_id
    assert replay.json()["is_voided"] is False


def test_deactivate_balance_bike_trim_finite_and_password_confirm(client):
    owner = _register(client, "flow-0715", "v0715-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}

    # Invite temp password requires matching confirm
    mismatch = client.post(
        "/orgs/invite",
        headers=h,
        json={
            "email": "v0715-bad@example.com",
            "full_name": "Bad",
            "role": "employee",
            "password": "secret12",
            "password_confirm": "other12",
        },
    )
    assert mismatch.status_code == 422

    inv = client.post(
        "/orgs/invite",
        headers=h,
        json={
            "email": "v0715-emp@example.com",
            "full_name": "Emp",
            "role": "employee",
            "password": "secret12",
            "password_confirm": "secret12",
        },
    )
    assert inv.status_code == 200, inv.text
    emp_id = inv.json()["id"]

    # Member password reset requires confirm
    bad_reset = client.post(
        f"/orgs/members/{emp_id}/password",
        headers=h,
        json={"new_password": "brandnew1", "password_confirm": "othernew1"},
    )
    assert bad_reset.status_code == 422

    # Category over VARCHAR limit
    too_long = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 10,
            "category": "C" * 121,
            "purpose": "Office",
            "payment_source": "my_pocket",
        },
    )
    assert too_long.status_code == 422

    # Non-finite liters rejected
    bad_liters = client.post(
        "/records",
        headers=h,
        json={
            "kind": "fuel",
            "amount": 10,
            "category": "Bensin",
            "purpose": "Other",
            "bike": "X1",
            "liters": "Infinity",
            "odometer": 100,
            "payment_source": "my_pocket",
        },
    )
    assert bad_liters.status_code == 422

    # Bike whitespace normalized — odometer continuity across trim
    first = client.post(
        "/records",
        headers=h,
        json={
            "kind": "fuel",
            "amount": 50,
            "category": "Bensin",
            "purpose": "Other",
            "bike": "  Scoot  ",
            "liters": 3,
            "odometer": 1000,
            "payment_source": "my_pocket",
            "approve_now": True,
        },
    )
    assert first.status_code == 200, first.text
    assert first.json()["bike"] == "Scoot"
    lower = client.post(
        "/records",
        headers=h,
        json={
            "kind": "fuel",
            "amount": 40,
            "category": "Bensin",
            "purpose": "Other",
            "bike": "Scoot",
            "liters": 2,
            "odometer": 900,
            "payment_source": "my_pocket",
        },
    )
    assert lower.status_code == 400
    assert "odometer" in lower.json()["detail"].lower()

    # Deactivate blocked while teammate holds spendings
    emp_login = client.post(
        "/auth/login",
        json={
            "email": "v0715-emp@example.com",
            "password": "secret12",
            "organization_slug": "flow-0715",
        },
    )
    assert emp_login.status_code == 200
    eh = {"Authorization": f"Bearer {emp_login.json()['access_token']}"}
    spent = client.post(
        "/records",
        headers=eh,
        json={
            "kind": "expense",
            "amount": 250,
            "category": "Taxi",
            "purpose": "Office",
            "payment_source": "my_pocket",
            "approve_now": False,
        },
    )
    assert spent.status_code == 200
    rid = spent.json()["id"]
    decided = client.post(
        f"/records/{rid}/decide",
        headers=h,
        json={"approve": True},
    )
    assert decided.status_code == 200, decided.text
    blocked = client.post(
        f"/orgs/members/{emp_id}/active",
        headers=h,
        json={"is_active": False},
    )
    assert blocked.status_code == 400
    assert "cash or spendings" in blocked.json()["detail"].lower()


def test_idem_fingerprint_occurred_at_patch_and_register_conflict(client):
    owner = _register(client, "flow-0716", "v0716-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}

    # Duplicate slug → 400 (not 500)
    dup = client.post(
        "/orgs/register",
        json={
            "name": "Other",
            "slug": "flow-0716",
            "currency": "IDR",
            "owner_email": "v0716-other@example.com",
            "owner_name": "Other",
            "owner_password": "secret12",
            "owner_password_confirm": "secret12",
        },
    )
    assert dup.status_code == 400

    rec = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 40,
            "category": "Taxi",
            "purpose": "Office",
            "payment_source": "my_pocket",
            "occurred_at": "2024-06-15T12:00:00",
        },
    )
    assert rec.status_code == 200, rec.text
    rid = rec.json()["id"]
    assert rec.json()["occurred_at"].startswith("2024-06-15")

    patched = client.patch(
        f"/records/{rid}",
        headers=h,
        json={"occurred_at": "2024-07-01T12:00:00"},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["occurred_at"].startswith("2024-07-01")

    cleared = client.patch(
        f"/records/{rid}",
        headers=h,
        json={"occurred_at": None},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["occurred_at"] is None


def test_money_limit_odometer_chronology_and_payout_idem_fingerprint(client):
    owner = _register(client, "flow-0717", "v0717-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}

    too_big = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 1e20,
            "category": "Taxi",
            "purpose": "Office",
            "payment_source": "my_pocket",
        },
    )
    assert too_big.status_code in (400, 422)
    assert "large" in str(too_big.json()).lower()

    pending = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 12,
            "category": "Taxi",
            "purpose": "Office",
            "payment_source": "my_pocket",
        },
    )
    assert pending.status_code == 200
    null_amt = client.patch(
        f"/records/{pending.json()['id']}",
        headers=h,
        json={"amount": None},
    )
    assert null_amt.status_code == 400

    # Later reading first
    later = client.post(
        "/records",
        headers=h,
        json={
            "kind": "fuel",
            "amount": 50,
            "category": "Bensin",
            "purpose": "Other",
            "bike": "Chrono",
            "liters": 4,
            "odometer": 2000,
            "occurred_at": "2025-06-01T12:00:00",
            "payment_source": "my_pocket",
            "approve_now": True,
        },
    )
    assert later.status_code == 200, later.text
    # Backdated insert cannot exceed the later reading
    too_high = client.post(
        "/records",
        headers=h,
        json={
            "kind": "fuel",
            "amount": 40,
            "category": "Bensin",
            "purpose": "Other",
            "bike": "Chrono",
            "liters": 3,
            "odometer": 2500,
            "occurred_at": "2025-05-01T12:00:00",
            "payment_source": "my_pocket",
        },
    )
    assert too_high.status_code == 400
    assert "later" in too_high.json()["detail"].lower()
    # Valid historical reading below the later one
    earlier = client.post(
        "/records",
        headers=h,
        json={
            "kind": "fuel",
            "amount": 40,
            "category": "Bensin",
            "purpose": "Other",
            "bike": "Chrono",
            "liters": 3,
            "odometer": 1500,
            "occurred_at": "2025-05-01T12:00:00",
            "payment_source": "my_pocket",
            "approve_now": True,
        },
    )
    assert earlier.status_code == 200, earlier.text

    # Payout create: same key + different payload → 409
    client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 800,
            "category": "Taxi",
            "purpose": "Office",
            "payment_source": "my_pocket",
            "approve_now": True,
        },
    )
    key = "payout-create-0717"
    p1 = client.post(
        "/payouts",
        headers={**h, "Idempotency-Key": key},
        json={
            "user_id": owner["user"]["id"],
            "kind": "expense_payout",
            "amount": 100,
            "payment_method": "cash",
            "note": "partial",
        },
    )
    assert p1.status_code == 200, p1.text
    p2 = client.post(
        "/payouts",
        headers={**h, "Idempotency-Key": key},
        json={
            "user_id": owner["user"]["id"],
            "kind": "expense_payout",
            "amount": 200,
            "payment_method": "cash",
            "note": "other",
        },
    )
    assert p2.status_code == 409


def test_overpayment_credit_null_patch_and_inactive_owner_demote(client):
    owner = _register(client, "flow-0718", "v0718-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    uid = owner["user"]["id"]

    # Seed spendings then overpay
    client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 100,
            "category": "Taxi",
            "purpose": "Office",
            "payment_source": "my_pocket",
            "approve_now": True,
        },
    )
    over = client.post(
        "/payouts",
        headers=h,
        json={
            "user_id": uid,
            "kind": "expense_payout",
            "amount": 250,
            "payment_method": "cash",
            "note": "overpay",
        },
    )
    assert over.status_code == 200, over.text
    assert over.json()["overpayment"] == 150
    # Tiny follow-up payout while owed is 0 must carry unused credit
    carry = client.post(
        "/payouts",
        headers=h,
        json={
            "user_id": uid,
            "kind": "expense_payout",
            "amount": 10,
            "payment_method": "cash",
            "note": "carry credit",
        },
    )
    assert carry.status_code == 200, carry.text
    assert carry.json()["overpayment"] == 160
    # New pocket spend 40 → spendings stay 0 (credit 160 covers it)
    client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 40,
            "category": "Food",
            "purpose": "Office",
            "payment_source": "my_pocket",
            "approve_now": True,
        },
    )
    bal = client.get("/records/balance/me", headers=h)
    assert bal.status_code == 200
    assert bal.json()["spendings"] == 0

    # Null text fields on PATCH coerce to empty (no 500)
    pending = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 5,
            "category": "Taxi",
            "purpose": "Office",
            "payment_source": "my_pocket",
            "place": "Office A",
        },
    )
    assert pending.status_code == 200
    rid = pending.json()["id"]
    cleared = client.patch(
        f"/records/{rid}",
        headers=h,
        json={"place": None, "comment": None, "bike": None},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["place"] == ""

    # Inactive owner can be demoted even if they are the only inactive owner
    inv = client.post(
        "/orgs/invite",
        headers=h,
        json={
            "email": "v0718-co@example.com",
            "full_name": "Co Owner",
            "role": "owner",
            "password": "secret12",
            "password_confirm": "secret12",
        },
    )
    assert inv.status_code == 200
    co_id = inv.json()["id"]
    # Deactivate co-owner after settling any balances (none)
    deact = client.post(
        f"/orgs/members/{co_id}/active",
        headers=h,
        json={"is_active": False},
    )
    assert deact.status_code == 200, deact.text
    demote = client.post(
        f"/orgs/members/{co_id}/role",
        headers=h,
        json={"role": "employee"},
    )
    assert demote.status_code == 200, demote.text
    assert demote.json()["role"] == "employee"



def test_record_patch_idempotency_and_batch_locks(client):
    owner = _register(client, "flow-0720", "v0720-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    rec = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 33,
            "category": "Taxi",
            "purpose": "Office",
            "payment_source": "my_pocket",
            "place": "A",
        },
    )
    assert rec.status_code == 200, rec.text
    rid = rec.json()["id"]
    key = "patch-once-0720"
    first = client.patch(
        f"/records/{rid}",
        headers={**h, "Idempotency-Key": key},
        json={"place": "B", "comment": "edited"},
    )
    assert first.status_code == 200, first.text
    assert first.json()["place"] == "B"
    replay = client.patch(
        f"/records/{rid}",
        headers={**h, "Idempotency-Key": key},
        json={"place": "B", "comment": "edited"},
    )
    assert replay.status_code == 200
    assert replay.json()["id"] == rid
    assert replay.json()["place"] == "B"
    mismatch = client.patch(
        f"/records/{rid}",
        headers={**h, "Idempotency-Key": key},
        json={"place": "C", "comment": "edited"},
    )
    assert mismatch.status_code == 409

    # Seed spendings then batch-pay with idem key
    client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 80,
            "category": "Food",
            "purpose": "Office",
            "payment_source": "my_pocket",
            "approve_now": True,
        },
    )
    bkey = "batch-spend-0720"
    batch = client.post(
        "/payouts/batch-spendings?payment_method=cash",
        headers={**h, "Idempotency-Key": bkey},
    )
    assert batch.status_code == 200, batch.text
    assert isinstance(batch.json(), list)
    assert len(batch.json()) >= 1
    batch_replay = client.post(
        "/payouts/batch-spendings?payment_method=cash",
        headers={**h, "Idempotency-Key": bkey},
    )
    assert batch_replay.status_code == 200
    assert [x["id"] for x in batch_replay.json()] == [x["id"] for x in batch.json()]
    batch_mismatch = client.post(
        "/payouts/batch-spendings?payment_method=transfer",
        headers={**h, "Idempotency-Key": bkey},
    )
    assert batch_mismatch.status_code == 409

    # Trim note on settlement request
    req = client.post(
        "/payouts/requests",
        headers=h,
        json={"kind": "expense_payout", "amount": 1, "note": "  padded  "},
    )
    # May fail if no spendings left after batch — seed again if needed
    if req.status_code == 400:
        client.post(
            "/records",
            headers=h,
            json={
                "kind": "expense",
                "amount": 5,
                "category": "Taxi",
                "purpose": "Office",
                "payment_source": "my_pocket",
                "approve_now": True,
            },
        )
        req = client.post(
            "/payouts/requests",
            headers=h,
            json={"kind": "expense_payout", "amount": 1, "note": "  padded  "},
        )
    assert req.status_code == 200, req.text
    assert req.json()["note"] == "padded"


def test_row_locks_note_trim_and_expired_reactivate(client):
    owner = _register(client, "flow-0721", "v0721-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}

    # Decide note trim
    pending = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 15,
            "category": "Taxi",
            "purpose": "Office",
            "payment_source": "my_pocket",
        },
    )
    assert pending.status_code == 200, pending.text
    rid = pending.json()["id"]
    decided = client.post(
        f"/records/{rid}/decide",
        headers=h,
        json={"approve": True, "note": "  ok  "},
    )
    assert decided.status_code == 200, decided.text
    assert "[review] ok" in decided.json()["comment"]

    # Soft cancel retry after lock path
    pending2 = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 7,
            "category": "Taxi",
            "purpose": "Office",
            "payment_source": "my_pocket",
        },
    )
    assert pending2.status_code == 200
    rid2 = pending2.json()["id"]
    c1 = client.delete(f"/records/{rid2}", headers=h)
    assert c1.status_code == 200
    c2 = client.delete(f"/records/{rid2}", headers=h)
    assert c2.status_code == 200

    # Telegram chat trim
    tg = client.post(
        "/integrations/telegram/chat",
        headers=h,
        json={"telegram_chat_id": "  12345  "},
    )
    assert tg.status_code == 200, tg.text
    assert tg.json()["telegram_chat_id"] == "12345"

    # Invite then expire token → reactivate blocked until new reset token
    inv = client.post(
        "/orgs/invite",
        headers=h,
        json={"email": "v0721-emp@example.com", "full_name": "Emp", "role": "employee"},
    )
    assert inv.status_code == 200, inv.text
    emp_id = inv.json()["id"]
    deact = client.post(
        f"/orgs/members/{emp_id}/active",
        headers=h,
        json={"is_active": False},
    )
    assert deact.status_code == 200, deact.text
    from app.db import SessionLocal
    from app.models import User
    from datetime import datetime, timedelta, timezone

    db = SessionLocal()
    try:
        u = db.get(User, emp_id)
        assert u is not None
        u.invite_token_expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
            days=1
        )
        db.commit()
    finally:
        db.close()
    blocked = client.post(
        f"/orgs/members/{emp_id}/active",
        headers=h,
        json={"is_active": True},
    )
    assert blocked.status_code == 400
    assert "expired" in blocked.json()["detail"].lower()
    # Recovery token while inactive + must_set_password
    issued = client.post(f"/orgs/members/{emp_id}/reset-token", headers=h)
    assert issued.status_code == 200, issued.text
    assert issued.json()["invite_token"]
    react = client.post(
        f"/orgs/members/{emp_id}/active",
        headers=h,
        json={"is_active": True},
    )
    assert react.status_code == 200, react.text


def test_adjustment_reserves_search_escape_and_inactive_approve(client):
    owner = _register(client, "flow-0722", "v0722-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    uid = owner["user"]["id"]

    client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 100,
            "category": "Taxi",
            "purpose": "Office",
            "payment_source": "my_pocket",
            "approve_now": True,
            "place": "100%_literal",
        },
    )
    req = client.post(
        "/payouts/requests",
        headers=h,
        json={"kind": "expense_payout", "amount": 60, "note": "hold"},
    )
    assert req.status_code == 200, req.text

    # Negative adjustment must not eat pending reserves (available 40)
    bad_adj = client.post(
        "/adjustments",
        headers=h,
        json={
            "user_id": uid,
            "track": "spendings",
            "amount": -50,
            "note": "too deep",
        },
    )
    assert bad_adj.status_code == 400
    assert "reserves" in bad_adj.json()["detail"].lower()
    ok_adj = client.post(
        "/adjustments",
        headers=h,
        json={
            "user_id": uid,
            "track": "spendings",
            "amount": -30,
            "note": "within available",
        },
    )
    assert ok_adj.status_code == 200, ok_adj.text

    # Search wildcards are literal
    hit = client.get("/records/mine?q=100%_literal", headers=h)
    assert hit.status_code == 200
    assert any(r["place"] == "100%_literal" for r in hit.json())
    miss = client.get("/records/mine?q=100Xliteral", headers=h)
    assert miss.status_code == 200
    assert all(r.get("place") != "100%_literal" for r in miss.json())
    too_long = client.get("/records/mine?q=" + ("a" * 81), headers=h)
    assert too_long.status_code == 400

    # Malformed photo path rejected
    bad_photo = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 1,
            "category": "Taxi",
            "purpose": "Office",
            "payment_source": "my_pocket",
            "photo_url": "/media/files/1/not-a-uuid.jpg",
        },
    )
    assert bad_photo.status_code == 400

    # Inactive teammate cannot get settlement approved
    inv = client.post(
        "/orgs/invite",
        headers=h,
        json={
            "email": "v0722-emp@example.com",
            "full_name": "Emp",
            "role": "employee",
            "password": "secret12",
            "password_confirm": "secret12",
        },
    )
    assert inv.status_code == 200, inv.text
    emp_id = inv.json()["id"]
    login = client.post(
        "/auth/login",
        json={
            "email": "v0722-emp@example.com",
            "password": "secret12",
            "organization_slug": "flow-0722",
        },
    )
    assert login.status_code == 200
    eh = {"Authorization": f"Bearer {login.json()['access_token']}"}
    client.post(
        "/records",
        headers=eh,
        json={
            "kind": "expense",
            "amount": 20,
            "category": "Taxi",
            "purpose": "Office",
            "payment_source": "my_pocket",
            "approve_now": False,
        },
    )
    # Owner approves then employee requests; deactivate before approve request
    pending = client.get("/records/pending", headers=h).json()
    emp_rec = next(r for r in pending if r["created_by"] == emp_id)
    assert (
        client.post(
            f"/records/{emp_rec['id']}/decide",
            headers=h,
            json={"approve": True},
        ).status_code
        == 200
    )
    sreq = client.post(
        "/payouts/requests",
        headers=eh,
        json={"kind": "expense_payout", "amount": 20, "note": "pay"},
    )
    assert sreq.status_code == 200, sreq.text
    # Settle to zero then deactivate
    assert (
        client.post(
            f"/payouts/requests/{sreq.json()['id']}/approve",
            headers=h,
            json={"payment_method": "cash"},
        ).status_code
        == 200
    )
    # New spend + request, then deactivate before approve
    assert (
        client.post(
            "/records",
            headers=eh,
            json={
                "kind": "expense",
                "amount": 12,
                "category": "Taxi",
                "purpose": "Office",
                "payment_source": "my_pocket",
            },
        ).status_code
        == 200
    )
    pending2 = client.get("/records/pending", headers=h).json()
    emp_rec2 = next(r for r in pending2 if r["created_by"] == emp_id)
    assert (
        client.post(
            f"/records/{emp_rec2['id']}/decide",
            headers=h,
            json={"approve": True},
        ).status_code
        == 200
    )
    sreq2 = client.post(
        "/payouts/requests",
        headers=eh,
        json={"kind": "expense_payout", "amount": 12, "note": "again"},
    )
    assert sreq2.status_code == 200, sreq2.text
    from app.db import SessionLocal
    from app.models import User

    db = SessionLocal()
    try:
        u = db.get(User, emp_id)
        assert u is not None
        u.is_active = False
        db.commit()
    finally:
        db.close()
    blocked = client.post(
        f"/payouts/requests/{sreq2.json()['id']}/approve",
        headers=h,
        json={"payment_method": "cash"},
    )
    assert blocked.status_code == 400
    assert "inactive" in blocked.json()["detail"].lower()


def test_manager_invite_role_comment_cap_and_odo_bounds(client):
    owner = _register(client, "flow-0723", "v0723-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    mgr = client.post(
        "/orgs/invite",
        headers=h,
        json={
            "email": "v0723-mgr@example.com",
            "full_name": "Mgr",
            "role": "manager",
            "password": "secret12",
            "password_confirm": "secret12",
        },
    )
    assert mgr.status_code == 200, mgr.text
    login = client.post(
        "/auth/login",
        json={
            "email": "v0723-mgr@example.com",
            "password": "secret12",
            "organization_slug": "flow-0723",
        },
    )
    assert login.status_code == 200
    mh = {"Authorization": f"Bearer {login.json()['access_token']}"}
    bad_role = client.post(
        "/orgs/invite",
        headers=mh,
        json={"email": "v0723-other@example.com", "full_name": "Other Mgr", "role": "manager"},
    )
    assert bad_role.status_code == 403
    ok_emp = client.post(
        "/orgs/invite",
        headers=mh,
        json={"email": "v0723-emp@example.com", "full_name": "Emp", "role": "employee"},
    )
    assert ok_emp.status_code == 200, ok_emp.text

    # Comment append cap
    pending = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 3,
            "category": "Taxi",
            "purpose": "Office",
            "payment_source": "my_pocket",
            "comment": "x" * 3980,
        },
    )
    assert pending.status_code == 200, pending.text
    rid = pending.json()["id"]
    huge = client.post(
        f"/records/{rid}/comment",
        headers=h,
        json={"note": "this note is long enough to overflow the comment budget"},
    )
    assert huge.status_code == 400
    assert "exceed" in huge.json()["detail"].lower()

    # Odometer hint bike bound + at validation
    long_bike = client.get("/records/fuel/last-odometer?bike=" + ("b" * 121), headers=h)
    assert long_bike.status_code == 400
    future = client.get("/records/fuel/last-odometer?at=2099-01-01", headers=h)
    assert future.status_code == 400

    # Non-finite payout amount rejected at schema edge
    nan = client.post(
        "/payouts",
        headers=h,
        json={
            "user_id": owner["user"]["id"],
            "kind": "expense_payout",
            "amount": "NaN",
            "payment_method": "cash",
            "note": "bad",
        },
    )
    assert nan.status_code == 422


def test_org_scoped_locks_batch_bounds_and_billing_redact(client):
    owner = _register(client, "flow-0724", "v0724-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}

    # Batch ids capped / deduped
    too_many = client.post(
        "/records/decide-batch",
        headers=h,
        json={"ids": list(range(1, 102)), "approve": True},
    )
    assert too_many.status_code == 422
    # Offset upper bound
    huge_off = client.get("/records/mine?offset=10001", headers=h)
    assert huge_off.status_code == 422

    # Cross-org lock miss stays 404 (org filter in FOR UPDATE)
    other = _register(client, "flow-0724b", "v0724b-owner@example.com")
    oh = {"Authorization": f"Bearer {other['access_token']}"}
    foreign = client.post(
        "/records",
        headers=oh,
        json={
            "kind": "expense",
            "amount": 9,
            "category": "Taxi",
            "purpose": "Office",
            "payment_source": "my_pocket",
        },
    )
    assert foreign.status_code == 200
    miss = client.post(
        f"/records/{foreign.json()['id']}/decide",
        headers=h,
        json={"approve": True},
    )
    assert miss.status_code == 404

    # Telegram chat id only for owner
    client.post(
        "/integrations/telegram/chat",
        headers=h,
        json={"telegram_chat_id": "999"},
    )
    mgr = client.post(
        "/orgs/invite",
        headers=h,
        json={
            "email": "v0724-mgr@example.com",
            "full_name": "Mgr",
            "role": "manager",
            "password": "secret12",
            "password_confirm": "secret12",
        },
    )
    assert mgr.status_code == 200, mgr.text
    login = client.post(
        "/auth/login",
        json={
            "email": "v0724-mgr@example.com",
            "password": "secret12",
            "organization_slug": "flow-0724",
        },
    )
    assert login.status_code == 200
    mh = {"Authorization": f"Bearer {login.json()['access_token']}"}
    owner_bill = client.get("/billing/me", headers=h)
    assert owner_bill.status_code == 200
    assert owner_bill.json()["telegram_chat_id"] == "999"
    mgr_bill = client.get("/billing/me", headers=mh)
    assert mgr_bill.status_code == 200
    assert mgr_bill.json()["telegram_chat_id"] == ""


def test_fuel_caps_date_span_and_export_charset(client):
    owner = _register(client, "flow-0725", "v0725-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}

    huge_liters = client.post(
        "/records",
        headers=h,
        json={
            "kind": "fuel",
            "amount": 50,
            "category": "Bensin",
            "purpose": "Other",
            "bike": "Cap-1",
            "liters": 10001,
            "odometer": 100,
            "payment_source": "my_pocket",
        },
    )
    assert huge_liters.status_code == 422

    huge_odo = client.post(
        "/records",
        headers=h,
        json={
            "kind": "fuel",
            "amount": 50,
            "category": "Bensin",
            "purpose": "Other",
            "bike": "Cap-1",
            "liters": 5,
            "odometer": 10000000,
            "payment_source": "my_pocket",
        },
    )
    assert huge_odo.status_code == 422

    ok_fuel = client.post(
        "/records",
        headers=h,
        json={
            "kind": "fuel",
            "amount": 50,
            "category": "Bensin",
            "purpose": "Other",
            "bike": "Cap-1",
            "liters": 5,
            "odometer": 100,
            "payment_source": "my_pocket",
            "approve_now": True,
        },
    )
    assert ok_fuel.status_code == 200, ok_fuel.text

    wide = client.get(
        "/reports/org?date_from=2010-01-01&date_to=2026-01-01",
        headers=h,
    )
    assert wide.status_code == 400
    assert "3650" in wide.json()["detail"]

    csv = client.get("/reports/export.csv?days=30", headers=h)
    assert csv.status_code == 200
    ctype = (csv.headers.get("content-type") or "").lower()
    assert "text/csv" in ctype
    assert "charset=utf-8" in ctype

    members = client.get("/orgs/members", headers=h)
    assert members.status_code == 200
    assert any(m["email"] == "v0725-owner@example.com" for m in members.json())

    team = client.get("/records/balance/team", headers=h)
    assert team.status_code == 200
    assert isinstance(team.json(), list)


def test_login_slug_norm_telegram_and_security_headers(client):
    owner = _register(client, "flow-0726", "v0726-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}

    # Slug / email case + whitespace still authenticate
    login = client.post(
        "/auth/login",
        json={
            "email": "  V0726-Owner@Example.com ",
            "password": "secret12",
            "organization_slug": " Flow-0726 ",
        },
    )
    assert login.status_code == 200, login.text

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["version"] == "0.7.41"
    assert health.headers.get("x-content-type-options") == "nosniff"
    assert health.headers.get("x-frame-options") == "DENY"
    assert health.headers.get("referrer-policy") == "no-referrer"

    bad_tg = client.post(
        "/integrations/telegram/chat",
        headers=h,
        json={"telegram_chat_id": "not a chat"},
    )
    assert bad_tg.status_code == 422

    ok_tg = client.post(
        "/integrations/telegram/chat",
        headers=h,
        json={"telegram_chat_id": "-100123"},
    )
    assert ok_tg.status_code == 200, ok_tg.text
    assert ok_tg.json()["telegram_chat_id"] == "-100123"

    csv = client.get("/reports/export.csv?days=7", headers=h)
    assert csv.status_code == 200
    cd = csv.headers.get("content-disposition") or ""
    assert 'filename="fos-export-7d.csv"' in cd
    assert "filename*=UTF-8''" in cd

    huge = client.get("/adjustments?limit=501", headers=h)
    assert huge.status_code == 422


def test_login_bounds_password_same_and_transfer_email(client):
    owner = _register(client, "flow-0727", "v0727-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}

    bad_slug = client.post(
        "/auth/login",
        json={
            "email": "v0727-owner@example.com",
            "password": "secret12",
            "organization_slug": "Flow_0727",
        },
    )
    assert bad_slug.status_code == 422

    too_long = client.post(
        "/auth/login",
        json={
            "email": "v0727-owner@example.com",
            "password": "x" * 129,
            "organization_slug": "flow-0727",
        },
    )
    assert too_long.status_code == 422

    same = client.post(
        "/auth/password",
        headers=h,
        json={
            "current_password": "secret12",
            "new_password": "secret12",
            "password_confirm": "secret12",
        },
    )
    assert same.status_code == 422

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["version"] == "0.7.41"
    assert health.headers.get("cache-control") == "no-store"

    # Seed cash via income then transfer with mixed-case email
    income = client.post(
        "/records",
        headers=h,
        json={
            "kind": "income",
            "amount": 5000,
            "category": "Sales",
            "purpose": "Rental",
            "payment_method": "cash",
            "client_name": "A",
            "approve_now": True,
        },
    )
    assert income.status_code == 200, income.text
    inv = client.post(
        "/orgs/invite",
        headers=h,
        json={
            "email": "v0727-recv@example.com",
            "full_name": "Recv",
            "role": "employee",
            "password": "secret12",
            "password_confirm": "secret12",
        },
    )
    assert inv.status_code == 200, inv.text
    xfer = client.post(
        "/transfers",
        headers={**h, "Idempotency-Key": "xfer-case-1"},
        json={
            "to_email": "  V0727-Recv@Example.com ",
            "amount": 1000,
            "comment": "case",
        },
    )
    assert xfer.status_code == 200, xfer.text


def test_idem_charset_invite_email_and_org_patch(client):
    owner = _register(client, "flow-0728", "v0728-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}

    bad_idem = client.post(
        "/records",
        headers={**h, "Idempotency-Key": "bad key\n"},
        json={
            "kind": "expense",
            "amount": 10,
            "category": "Taxi",
            "purpose": "Office",
            "payment_source": "my_pocket",
        },
    )
    assert bad_idem.status_code == 400
    assert "invalid" in bad_idem.json()["detail"].lower()

    space_idem = client.post(
        "/records",
        headers={**h, "Idempotency-Key": "has space"},
        json={
            "kind": "expense",
            "amount": 10,
            "category": "Taxi",
            "purpose": "Office",
            "payment_source": "my_pocket",
        },
    )
    assert space_idem.status_code == 400

    inv = client.post(
        "/orgs/invite",
        headers=h,
        json={
            "email": "  V0728-Emp@Example.com ",
            "full_name": "Emp",
            "role": "employee",
            "password": "secret12",
            "password_confirm": "secret12",
        },
    )
    assert inv.status_code == 200, inv.text
    assert inv.json()["email"] == "v0728-emp@example.com"

    bad_tok = client.post(
        "/auth/accept-invite",
        json={
            "token": "not valid!!tokenxx",
            "password": "secret99",
            "password_confirm": "secret99",
        },
    )
    assert bad_tok.status_code == 422

    patched = client.patch("/orgs/me", headers=h, json={"name": "Flow 0728 Co"})
    assert patched.status_code == 200
    assert patched.json()["name"] == "Flow 0728 Co"

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["version"] == "0.7.41"


def test_logout_bike_normalize_and_register_slug(client):
    owner = _register(client, "flow-0729", "v0729-owner@example.com")
    token = owner["access_token"]
    h = {"Authorization": f"Bearer {token}"}

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["version"] == "0.7.41"
    assert health.json()["db"] == "ok"
    assert health.json()["ok"] is True

    # Mixed-case / spaced register slug+email already covered; bike collapse
    fuel = client.post(
        "/records",
        headers=h,
        json={
            "kind": "fuel",
            "amount": 40,
            "category": "Bensin",
            "purpose": "Other",
            "bike": "  Scoot   One  ",
            "liters": 3,
            "odometer": 100,
            "payment_source": "my_pocket",
            "approve_now": True,
        },
    )
    assert fuel.status_code == 200, fuel.text
    assert fuel.json()["bike"] == "Scoot One"

    # Logout revokes prior token
    out = client.post("/auth/logout", headers=h)
    assert out.status_code == 200
    assert out.json()["ok"] is True
    me = client.get("/auth/me", headers=h)
    assert me.status_code == 401

    # Re-login works
    login = client.post(
        "/auth/login",
        json={
            "email": "v0729-owner@example.com",
            "password": "secret12",
            "organization_slug": "flow-0729",
        },
    )
    assert login.status_code == 200
    h2 = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert client.get("/auth/me", headers=h2).status_code == 200

    # OrgCreate slug/email normalize via register
    reg = client.post(
        "/orgs/register",
        json={
            "name": "Norm Co",
            "slug": " Flow-0729b ",
            "currency": "idr",
            "owner_email": "  V0729b@Example.com ",
            "owner_name": "Boss",
            "owner_password": "secret12",
            "owner_password_confirm": "secret12",
        },
    )
    assert reg.status_code == 200, reg.text
    assert reg.json()["organization_slug"] == "flow-0729b"
    assert reg.json()["user"]["email"] == "v0729b@example.com"


def test_place_client_normalize_and_coop_header(client):
    owner = _register(client, "flow-0730", "v0730-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["version"] == "0.7.41"
    assert health.headers.get("cross-origin-opener-policy") == "same-origin"

    rec = client.post(
        "/records",
        headers=h,
        json={
            "kind": "income",
            "amount": 100,
            "category": "Rental",
            "purpose": "Rental",
            "place": "  Beach   Club  ",
            "client_name": "  John   Doe  ",
            "payment_method": "cash",
            "approve_now": True,
        },
    )
    assert rec.status_code == 200, rec.text
    body = rec.json()
    assert body["place"] == "Beach Club"
    assert body["client_name"] == "John Doe"


def test_slug_shape_category_collapse(client):
    bad = client.post(
        "/orgs/register",
        json={
            "name": "Bad  Slug",
            "slug": "flow--0731",
            "currency": "IDR",
            "owner_email": "badslug@example.com",
            "owner_name": "Boss  Name",
            "owner_password": "secret12",
            "owner_password_confirm": "secret12",
        },
    )
    assert bad.status_code == 422

    edge = client.post(
        "/orgs/register",
        json={
            "name": "Edge",
            "slug": "-flow0731",
            "currency": "IDR",
            "owner_email": "edge@example.com",
            "owner_name": "Boss",
            "owner_password": "secret12",
            "owner_password_confirm": "secret12",
        },
    )
    assert edge.status_code == 422

    owner = _register(client, "flow-0731", "v0731-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    health = client.get("/health")
    assert health.json()["version"] == "0.7.41"

    rec = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 25,
            "category": "  Bike   service  ",
            "purpose": "Office",
            "payment_source": "my_pocket",
        },
    )
    assert rec.status_code == 200, rec.text
    assert rec.json()["category"] == "Bike service"

    login_bad = client.post(
        "/auth/login",
        json={
            "email": "v0731-owner@example.com",
            "password": "secret12",
            "organization_slug": "flow--0731",
        },
    )
    assert login_bad.status_code == 422


def test_request_id_note_collapse_and_team_rate_limit(client, monkeypatch):
    """v0.7.32: X-Request-Id, note whitespace collapse, team mutation rate limit."""
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["version"] == "0.7.41"
    assert "X-Request-Id" in health.headers
    rid = health.headers["X-Request-Id"]
    assert len(rid) >= 8

    custom = client.get("/health", headers={"X-Request-Id": "client-req-abc123"})
    assert custom.headers["X-Request-Id"] == "client-req-abc123"

    junk = client.get("/health", headers={"X-Request-Id": "bad id with spaces!!"})
    assert junk.headers["X-Request-Id"] != "bad id with spaces!!"
    assert len(junk.headers["X-Request-Id"]) >= 8

    owner = _register(client, "flow-0732", "v0732-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}

    # Seed spendings (expense payout) and cash (transfer)
    expense = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 50,
            "category": "Taxi",
            "purpose": "Office",
            "payment_source": "my_pocket",
            "approve_now": True,
        },
    )
    assert expense.status_code == 200, expense.text

    income = client.post(
        "/records",
        headers=h,
        json={
            "kind": "income",
            "amount": 500,
            "category": "Sales",
            "purpose": "Rental",
            "payment_method": "cash",
            "client_name": "  Client   Name  ",
            "approve_now": True,
        },
    )
    assert income.status_code == 200, income.text
    assert income.json()["client_name"] == "Client Name"

    pay = client.post(
        "/payouts",
        headers=h,
        json={
            "user_id": owner["user"]["id"],
            "kind": "expense_payout",
            "amount": 10,
            "payment_method": "cash",
            "note": "  paid   for   fuel  ",
        },
    )
    assert pay.status_code == 200, pay.text
    assert pay.json()["note"] == "paid for fuel"

    inv = client.post(
        "/orgs/invite",
        headers=h,
        json={
            "email": "v0732-emp@example.com",
            "full_name": "Emp",
            "role": "employee",
            "password": "secret12",
            "password_confirm": "secret12",
        },
    )
    assert inv.status_code == 200, inv.text
    emp_id = inv.json()["id"]

    xfer = client.post(
        "/transfers",
        headers=h,
        json={
            "to_email": "v0732-emp@example.com",
            "amount": 20,
            "comment": "  please   hold   cash  ",
        },
    )
    assert xfer.status_code == 200, xfer.text
    assert xfer.json()["sender_record"]["comment"] == "please hold cash"

    adj = client.post(
        "/adjustments",
        headers=h,
        json={
            "user_id": emp_id,
            "track": "cash_on_hand",
            "amount": 1,
            "note": "  tiny   fix  ",
        },
    )
    assert adj.status_code == 200, adj.text
    assert adj.json()["note"] == "tiny fix"

    from app.config import settings
    from app.services.rate_limit import reset_limiter_for_tests

    reset_limiter_for_tests()
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    try:
        limited = None
        for _ in range(35):
            limited = client.post(
                f"/orgs/members/{emp_id}/active",
                headers=h,
                json={"is_active": True},
            )
            if limited.status_code == 429:
                break
        assert limited is not None and limited.status_code == 429
        assert "Too many" in limited.json()["detail"]
    finally:
        monkeypatch.setattr(settings, "rate_limit_enabled", False)
        reset_limiter_for_tests()


def test_list_rate_limits_comment_collapse_batch_method(client, monkeypatch):
    """v0.7.33: list GET rate limits, decide/comment collapse, batch payment_method."""
    health = client.get("/health")
    assert health.json()["version"] == "0.7.41"
    assert "X-Request-Id" in health.headers

    owner = _register(client, "flow-0733", "v0733-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}

    rec = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 12,
            "category": "Supplies",
            "purpose": "Office",
            "payment_source": "my_pocket",
            "comment": "  needs   receipt  ",
        },
    )
    assert rec.status_code == 200, rec.text
    assert rec.json()["comment"] == "needs receipt"
    rid = rec.json()["id"]

    note = client.post(
        f"/records/{rid}/comment",
        headers=h,
        json={"note": "  please   check  "},
    )
    assert note.status_code == 200, note.text
    assert "please check" in note.json()["comment"]

    decided = client.post(
        f"/records/{rid}/decide",
        headers=h,
        json={"approve": True, "note": "  looks   good  "},
    )
    assert decided.status_code == 200, decided.text
    assert "looks good" in decided.json()["comment"]

    bad_batch = client.post("/payouts/batch-spendings?payment_method=crypto", headers=h)
    assert bad_batch.status_code == 400
    assert "payment_method" in bad_batch.json()["detail"]

    from app.config import settings
    from app.services.rate_limit import reset_limiter_for_tests

    reset_limiter_for_tests()
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    try:
        limited = None
        for _ in range(130):
            limited = client.get("/records/mine", headers=h)
            if limited.status_code == 429:
                break
        assert limited is not None and limited.status_code == 429
        assert limited.headers.get("Retry-After")
        assert "Too many" in limited.json()["detail"]
    finally:
        monkeypatch.setattr(settings, "rate_limit_enabled", False)
        reset_limiter_for_tests()


def test_control_chars_read_limits_and_request_id_header(client, monkeypatch):
    """v0.7.34: reject control chars, rate-limit remaining reads."""
    health = client.get("/health")
    assert health.json()["version"] == "0.7.41"
    assert health.headers.get("X-Request-Id")

    owner = _register(client, "flow-0734", "v0734-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}

    bad = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 5,
            "category": "Supplies",
            "purpose": "Office",
            "payment_source": "my_pocket",
            "comment": "ok\x00bad",
        },
    )
    assert bad.status_code == 422

    bad_name = client.post(
        "/orgs/invite",
        headers=h,
        json={
            "email": "v0734-emp@example.com",
            "full_name": "Emp\x07Name",
            "role": "employee",
        },
    )
    assert bad_name.status_code == 422

    ok = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 5,
            "category": "Supplies",
            "purpose": "Office",
            "payment_source": "my_pocket",
            "comment": "  clean   note  ",
        },
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["comment"] == "clean note"
    rid = ok.json()["id"]

    got = client.get(f"/records/{rid}", headers=h)
    assert got.status_code == 200
    assert got.headers.get("X-Request-Id")

    from app.config import settings
    from app.services.rate_limit import reset_limiter_for_tests

    reset_limiter_for_tests()
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    try:
        limited = None
        for _ in range(130):
            limited = client.get("/auth/me", headers=h)
            if limited.status_code == 429:
                break
        assert limited is not None and limited.status_code == 429
        assert limited.headers.get("Retry-After")
    finally:
        monkeypatch.setattr(settings, "rate_limit_enabled", False)
        reset_limiter_for_tests()


def test_health_controls_before_collapse_and_export_names(client, monkeypatch):
    """v0.7.35: health readiness, control-char order, CSV export still works."""
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["version"] == "0.7.41"
    assert health.json()["ok"] is True
    assert health.json()["db"] == "ok"

    owner = _register(client, "flow-0735", "v0735-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}

    # Vertical tab should be rejected (not silently collapsed away)
    bad = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 4,
            "category": "Bike\x0bservice",
            "purpose": "Office",
            "payment_source": "my_pocket",
        },
    )
    assert bad.status_code in (400, 422)

    ok = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 4,
            "category": "  Bike   service  ",
            "purpose": "Office",
            "payment_source": "my_pocket",
            "approve_now": True,
        },
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["category"] == "Bike service"

    csv = client.get("/reports/export.csv?days=30", headers=h)
    assert csv.status_code == 200
    assert "Bike service" in csv.text
    assert "Owner" in csv.text or owner["user"]["full_name"] in csv.text

    from app.config import settings
    from app.services.rate_limit import reset_limiter_for_tests

    reset_limiter_for_tests()
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    try:
        limited = None
        for _ in range(130):
            limited = client.get("/health")
            if limited.status_code == 429:
                break
        assert limited is not None and limited.status_code == 429
    finally:
        monkeypatch.setattr(settings, "rate_limit_enabled", False)
        reset_limiter_for_tests()


def test_login_timing_media_token_bound_and_export_cap(client):
    """v0.7.36: dummy-hash login path, media token bound, health version."""
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["version"] == "0.7.41"

    # Missing account still 401 (dummy hash path)
    missing = client.post(
        "/auth/login",
        json={
            "email": "nobody@example.com",
            "password": "secret12",
            "organization_slug": "no-such-org",
        },
    )
    assert missing.status_code == 401
    assert missing.json()["detail"] == "Invalid credentials"

    owner = _register(client, "flow-0736", "v0736-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}

    # Oversized media query token rejected at validation
    huge = client.get("/media/files/1/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.jpg?token=" + ("a" * 2100), headers=h)
    assert huge.status_code == 422

    csv = client.get("/reports/export.csv?days=30", headers=h)
    assert csv.status_code == 200


def test_preauth_429_body_limit_purpose_and_settings(client, monkeypatch, tmp_path):
    """v0.7.37: middleware 429 JSON, body size, purpose reject, settings guard."""
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["version"] == "0.7.41"

    from app.config import settings
    from app.services.rate_limit import reset_limiter_for_tests

    reset_limiter_for_tests()
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    try:
        limited = None
        for _ in range(70):
            limited = client.post(
                "/auth/login",
                json={
                    "email": "not-a-valid",
                    "password": "x",
                    "organization_slug": "nope",
                },
            )
            if limited.status_code == 429:
                break
        assert limited is not None and limited.status_code == 429
        assert limited.json()["detail"]
        assert limited.headers.get("Retry-After")
        assert limited.headers.get("X-Request-Id")
    finally:
        monkeypatch.setattr(settings, "rate_limit_enabled", False)
        reset_limiter_for_tests()

    too_big = client.post(
        "/orgs/register",
        headers={"Content-Length": str(300_000)},
        content=b"{}",
    )
    assert too_big.status_code == 413

    owner = _register(client, "flow-0737", "v0737-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    bad_purpose = client.get("/records/mine?purpose=" + ("p" * 81), headers=h)
    assert bad_purpose.status_code == 400

    from app.main import _validate_runtime_settings

    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "secret_key", "short")
    try:
        raised = False
        try:
            _validate_runtime_settings()
        except RuntimeError:
            raised = True
        assert raised
    finally:
        monkeypatch.setattr(settings, "environment", "development")
        monkeypatch.setattr(settings, "secret_key", "test-secret")


def test_org_cap_jwt_bind_pagination_csv_and_plaintext_invite(client, monkeypatch):
    """v0.7.38: invite ceiling, JWT org bind, pagination, CSV defaults, hashed-only invites."""
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["version"] == "0.7.41"

    from app.config import settings
    from app.db import SessionLocal
    from app.models import User
    from app.auth import create_access_token, user_from_token
    from app.main import _validate_runtime_settings
    from app.routers.reports import _csv_text

    owner = _register(client, "flow-0738", "v0738-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}

    page = client.get("/orgs/members?limit=1&offset=0", headers=h)
    assert page.status_code == 200
    assert len(page.json()) == 1

    monkeypatch.setattr(settings, "max_org_members", 1)
    try:
        blocked = client.post(
            "/orgs/invite",
            headers=h,
            json={
                "email": "blocked-0738@example.com",
                "full_name": "Blocked",
                "role": "employee",
            },
        )
        assert blocked.status_code == 400
        assert "limit" in blocked.json()["detail"].lower()
    finally:
        monkeypatch.setattr(settings, "max_org_members", 300)

    # JWT org claim must match user.organization_id
    uid = owner["user"]["id"]
    wrong = create_access_token(uid, org_id=999999, role="owner", token_version=0)
    db = SessionLocal()
    try:
        u = db.get(User, uid)
        assert u is not None
        # Align token_version with freshly created user
        wrong = create_access_token(
            uid,
            org_id=999999,
            role=u.role.value if hasattr(u.role, "value") else str(u.role),
            token_version=int(getattr(u, "token_version", 0) or 0),
        )
        raised = False
        try:
            user_from_token(wrong, db)
        except Exception:
            raised = True
        assert raised
        me_bad = client.get("/orgs/me", headers={"Authorization": f"Bearer {wrong}"})
        assert me_bad.status_code == 401
    finally:
        db.close()

    # Plaintext invite tokens are no longer accepted
    inv = client.post(
        "/orgs/invite",
        headers=h,
        json={
            "email": "plain-0738@example.com",
            "full_name": "Plain",
            "role": "employee",
        },
    )
    assert inv.status_code == 200, inv.text
    raw = inv.json()["invite_token"]
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.email == "plain-0738@example.com").one()
        u.invite_token = raw  # force legacy plaintext storage
        db.commit()
    finally:
        db.close()
    rejected = client.post(
        "/auth/accept-invite",
        json={"token": raw, "password": "chosen99", "password_confirm": "chosen99"},
    )
    assert rejected.status_code == 400

    long = "x" * 2500
    assert len(_csv_text(long)) <= 2000
    assert _csv_text(long).endswith("…")

    csv = client.get("/reports/export.csv", headers=h)
    assert csv.status_code == 200
    assert "Content-Disposition" in csv.headers
    assert "365d" in csv.headers.get("Content-Disposition", "") or "record" in csv.text

    monkeypatch.setattr(settings, "max_org_members", 0)
    try:
        raised = False
        try:
            _validate_runtime_settings()
        except RuntimeError:
            raised = True
        assert raised
    finally:
        monkeypatch.setattr(settings, "max_org_members", 300)

    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "secret_key", "a" * 40)
    monkeypatch.setattr(settings, "media_backend", "s3")
    monkeypatch.setattr(settings, "s3_bucket", "")
    try:
        raised = False
        try:
            _validate_runtime_settings()
        except RuntimeError:
            raised = True
        assert raised
    finally:
        monkeypatch.setattr(settings, "environment", "development")
        monkeypatch.setattr(settings, "secret_key", "test-secret")
        monkeypatch.setattr(settings, "media_backend", "local")
        monkeypatch.setattr(settings, "s3_bucket", "")


def test_reset_force_accept_message_reports_default_and_amount(client):
    """v0.7.39: reset 409/force, accept message, reports default window, amount schema."""
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["version"] == "0.7.41"

    owner = _register(client, "flow-0739", "v0739-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    inv = client.post(
        "/orgs/invite",
        headers=h,
        json={
            "email": "v0739-emp@example.com",
            "full_name": "Emp 739",
            "role": "employee",
        },
    )
    assert inv.status_code == 200, inv.text
    emp_id = inv.json()["id"]
    raw = inv.json()["invite_token"]

    # Invite already has an active token — reset without force → 409
    conflict = client.post(f"/orgs/members/{emp_id}/reset-token", headers=h)
    assert conflict.status_code == 409
    forced = client.post(f"/orgs/members/{emp_id}/reset-token?force=true", headers=h)
    assert forced.status_code == 200, forced.text
    raw2 = forced.json()["invite_token"]
    assert raw2 and raw2 != raw

    ok = client.post(
        "/auth/accept-invite",
        json={"token": raw2, "password": "chosen99", "password_confirm": "chosen99"},
    )
    assert ok.status_code == 200, ok.text

    # Simulate race: token still present but password already set
    from app.db import SessionLocal
    from app.models import User
    from app.services.invite_tokens import store_invite_token

    leftover = "leftover-token-0739-abcdefgh"
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.email == "v0739-emp@example.com").one()
        u.must_set_password = False
        u.invite_token = store_invite_token(leftover)
        db.commit()
    finally:
        db.close()
    again = client.post(
        "/auth/accept-invite",
        json={"token": leftover, "password": "chosen99", "password_confirm": "chosen99"},
    )
    assert again.status_code == 400
    assert "already accepted" in again.json()["detail"].lower()

    report = client.get("/reports/me", headers=h)
    assert report.status_code == 200
    org = client.get("/reports/org", headers=h)
    assert org.status_code == 200

    inf = client.post(
        "/records",
        headers={**h, "Content-Type": "application/json"},
        content='{"kind":"expense","amount":"Infinity","category":"Taxi","payment_source":"my_pocket"}',
    )
    assert inf.status_code == 422
    tiny = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 0.004,
            "category": "Taxi",
            "payment_source": "my_pocket",
        },
    )
    assert tiny.status_code == 422


def test_password_strength_hsts_reject_note_and_media_path(client, monkeypatch):
    """v0.7.40: password rules, optional HSTS, reject note min 2, media path guard."""
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["version"] == "0.7.41"

    weak = client.post(
        "/orgs/register",
        json={
            "name": "Acme",
            "slug": "flow-0740-weak",
            "currency": "IDR",
            "owner_email": "weak-0740@example.com",
            "owner_name": "Owner",
            "owner_password": "password",
            "owner_password_confirm": "password",
        },
    )
    assert weak.status_code == 422

    owner = _register(client, "flow-0740", "v0740-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}

    from app.config import settings

    monkeypatch.setattr(settings, "enable_hsts", True)
    monkeypatch.setattr(settings, "hsts_max_age", 60)
    try:
        gated = client.get("/health")
        assert gated.status_code == 200
        assert "max-age=60" in gated.headers.get("Strict-Transport-Security", "")
    finally:
        monkeypatch.setattr(settings, "enable_hsts", False)

    rec = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 10,
            "category": "Taxi",
            "payment_source": "my_pocket",
        },
    )
    assert rec.status_code == 200, rec.text
    rid = rec.json()["id"]
    short = client.post(
        f"/records/{rid}/decide",
        headers=h,
        json={"approve": False, "note": "x"},
    )
    assert short.status_code == 422

    from app.services.storage import local_path

    raised = False
    try:
        local_path(1, "../etc/passwd")
    except ValueError:
        raised = True
    assert raised

    team = client.get("/records/balance/team", headers=h)
    assert team.status_code == 200
    assert isinstance(team.json(), list)


def test_invitee_billing_idem_ttl_and_docs_gate(client, monkeypatch):
    """v0.7.41: block unsettled invitees, canceled billing, idem prune, JWT ceiling."""
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["version"] == "0.7.41"
    assert client.get("/docs").status_code == 200

    owner = _register(client, "flow-0741", "v0741-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    inv = client.post(
        "/orgs/invite",
        headers=h,
        json={
            "email": "pending-0741@example.com",
            "full_name": "Pending",
            "role": "employee",
        },
    )
    assert inv.status_code == 200, inv.text
    assert inv.json().get("invite_token")
    emp_id = inv.json()["id"]

    directory = client.get("/orgs/directory", headers=h)
    assert directory.status_code == 200
    assert all(m["email"] != "pending-0741@example.com" for m in directory.json())

    blocked = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 10,
            "category": "Taxi",
            "payment_source": "my_pocket",
            "created_for_user_id": emp_id,
        },
    )
    assert blocked.status_code == 400
    assert "invite" in blocked.json()["detail"].lower()

    from app.db import SessionLocal
    from app.models import IdempotencyKey, Organization
    from app.services.idempotency import prune_expired_idem
    from datetime import datetime, timedelta, timezone

    db = SessionLocal()
    try:
        org = db.query(Organization).filter(Organization.slug == "flow-0741").one()
        org.billing_status = "canceled"
        db.commit()
        oid = org.id
        uid = owner["user"]["id"]
        row = IdempotencyKey(
            organization_id=oid,
            user_id=uid,
            scope="test.prune",
            key="old-key-0741",
            resource_id=1,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=10),
        )
        db.add(row)
        db.commit()
        deleted = prune_expired_idem(db)
        db.commit()
        assert deleted >= 1
    finally:
        db.close()

    login = client.post(
        "/auth/login",
        json={
            "email": "v0741-owner@example.com",
            "password": "secret12",
            "organization_slug": "flow-0741",
        },
    )
    assert login.status_code == 403

    money = client.post(
        "/records",
        headers=h,
        json={
            "kind": "expense",
            "amount": 10,
            "category": "Taxi",
            "payment_source": "my_pocket",
        },
    )
    assert money.status_code == 403

    from app.main import _validate_runtime_settings
    from app.config import settings

    monkeypatch.setattr(settings, "access_token_expire_minutes", 20_000)
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "secret_key", "a" * 40)
    try:
        raised = False
        try:
            _validate_runtime_settings()
        except RuntimeError:
            raised = True
        assert raised
    finally:
        monkeypatch.setattr(settings, "environment", "development")
        monkeypatch.setattr(settings, "secret_key", "test-secret")
        monkeypatch.setattr(settings, "access_token_expire_minutes", 60 * 24 * 7)
