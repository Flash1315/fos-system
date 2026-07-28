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
        json={"email": "xfer2-recv@example.com", "full_name": "Recv", "role": "employee", "password": "secret12"},
    )
    denied = client.post(
        "/transfers",
        headers=oh,
        json={"to_email": "xfer2-recv@example.com", "amount": 999999, "comment": "too much"},
    )
    assert denied.status_code == 400
    assert "Insufficient cash" in denied.json()["detail"]



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
    assert again.status_code == 400


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
    client.post(f"/records/{late.json()['id']}/decide", headers=h, json={"approve": True})
    assert client.get("/records/balance/me", headers=h).json()["spendings"] == 0
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


def test_password_and_settlement_request(client):
    owner = _register(client, "flow-acct", "acct-owner@example.com")
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    bad = client.post(
        "/auth/password",
        headers=h,
        json={"current_password": "wrong", "new_password": "newsecret"},
    )
    assert bad.status_code == 400
    ok = client.post(
        "/auth/password",
        headers=h,
        json={"current_password": "secret12", "new_password": "newsecret"},
    )
    assert ok.status_code == 200

    inv = client.post(
        "/orgs/invite",
        headers=h,
        json={
            "email": "acct-emp@example.com",
            "full_name": "Emp",
            "role": "employee",
            "password": "secret12",
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
        json={"kind": "income_handover", "amount": 15000, "note": "eod"},
    )
    assert req.status_code == 200
    mine = client.get("/payouts/requests/mine", headers=h)
    assert mine.status_code == 200
    assert any(x["id"] == req.json()["id"] for x in mine.json())

    batch = client.post("/payouts/batch-cash?payment_method=cash", headers=h)
    assert batch.status_code == 200, batch.text
    assert len(batch.json()) >= 1
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
        },
    )
    assert inv.status_code == 200
    emp_id = inv.json()["id"]
    reset = client.post(
        f"/orgs/members/{emp_id}/password",
        headers=h,
        json={"new_password": "brandnew1"},
    )
    assert reset.status_code == 200, reset.text
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
    all_time = client.get("/reports/org", headers=h)
    assert all_time.json()["approved_expense_total"] == 350
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
    assert "Insufficient cash" in denied.json()["detail"]
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
    again = client.post(f"/records/{rid}/void", headers=h, json={"note": "x"})
    assert again.status_code == 400

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
