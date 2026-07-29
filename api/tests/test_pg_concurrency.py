"""Focused PostgreSQL concurrency checks.

These tests intentionally share a TestClient across worker threads so requests
reach separate database sessions at nearly the same time.
"""

import os
import threading
from uuid import uuid4

import pytest


DATABASE_URL = os.environ.get("DATABASE_URL", "")
IS_POSTGRES = DATABASE_URL.startswith("postgresql")
pytestmark = pytest.mark.skipif(
    not IS_POSTGRES,
    reason="PostgreSQL concurrency tests require a PostgreSQL DATABASE_URL",
)
if IS_POSTGRES:
    pytest.importorskip("psycopg2")
    from fastapi.testclient import TestClient

    from app.main import app


@pytest.fixture(scope="module")
def pg_client():
    suffix = uuid4().hex[:12]
    with TestClient(app) as client:
        registered = client.post(
            "/orgs/register",
            json={
                "name": "PG Concurrency",
                "slug": f"pg-concurrency-{suffix}",
                "currency": "IDR",
                "owner_email": f"pg-concurrency-{suffix}@example.com",
                "owner_name": "PG Owner",
                "owner_password": "secret12",
                "owner_password_confirm": "secret12",
            },
        )
        assert registered.status_code == 200, registered.text
        headers = {"Authorization": f"Bearer {registered.json()['access_token']}"}
        yield client, headers


def _parallel_posts(client, url, *, headers, json):
    barrier = threading.Barrier(2)
    responses = [None, None]
    errors = []

    def post(index):
        try:
            barrier.wait(timeout=10)
            responses[index] = client.post(url, headers=headers, json=json)
        except BaseException as exc:  # surfaced in the main pytest thread below
            errors.append(exc)

    threads = [threading.Thread(target=post, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert not any(thread.is_alive() for thread in threads), "parallel request timed out"
    assert not errors, errors
    return responses


def test_parallel_idempotent_record_create_has_one_resource(pg_client):
    client, auth = pg_client
    marker = f"parallel-create-{uuid4().hex}"
    headers = {**auth, "Idempotency-Key": marker}
    payload = {
        "kind": "expense",
        "amount": 1234,
        "category": "supplies",
        "comment": marker,
    }

    responses = _parallel_posts(
        client,
        "/records",
        headers=headers,
        json=payload,
    )

    assert {response.status_code for response in responses} <= {200, 409}, [
        (response.status_code, response.text) for response in responses
    ]
    successful_ids = [
        response.json()["id"] for response in responses if response.status_code == 200
    ]
    assert successful_ids
    assert len(set(successful_ids)) == 1

    mine = client.get("/records/mine?limit=100", headers=auth)
    assert mine.status_code == 200, mine.text
    matching = [record for record in mine.json() if record["comment"] == marker]
    assert len(matching) == 1
    assert matching[0]["id"] == successful_ids[0]


def test_parallel_decisions_do_not_double_approve(pg_client):
    client, auth = pg_client
    created = client.post(
        "/records",
        headers=auth,
        json={
            "kind": "expense",
            "amount": 777,
            "category": "supplies",
            "comment": "parallel decision",
        },
    )
    assert created.status_code == 200, created.text
    record_id = created.json()["id"]

    responses = _parallel_posts(
        client,
        f"/records/{record_id}/decide",
        headers=auth,
        json={"approve": True, "note": "concurrent approval"},
    )

    assert {response.status_code for response in responses} <= {200, 400, 409}, [
        (response.status_code, response.text) for response in responses
    ]
    successes = [response.json() for response in responses if response.status_code == 200]
    assert successes
    assert {response["id"] for response in successes} == {record_id}
    assert {response["status"] for response in successes} == {"approved"}

    final = client.get(f"/records/{record_id}", headers=auth)
    assert final.status_code == 200, final.text
    assert final.json()["status"] == "approved"
    assert final.json()["comment"].count("[review] concurrent approval") == 1

    report = client.get("/reports/org", headers=auth)
    assert report.status_code == 200, report.text
    assert report.json()["approved_expense_total"] == 777
