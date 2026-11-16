"""A-02 단위 테스트(PostgREST는 respx 가짜)."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from tests.conftest import WORKSPACE_ID
from tests.read_api.conftest import REST

VIEW_URL = f"{REST}/candidate_list_v"
CANDIDATES_URL = f"{REST}/candidates"
PROFILES_URL = f"{REST}/profiles"
P1 = "00000000-0000-4000-8000-000000000101"
CID = "00000000-0000-4000-8000-000000000201"
VIEW_COUNTS = {"eq.producible": 3, "eq.pending": 1}


def view_head(request: httpx.Request) -> httpx.Response:
    n = VIEW_COUNTS[request.url.params["display_status"]]
    return httpx.Response(200, headers={"Content-Range": f"0-{n - 1}/{n}"})


@pytest.fixture
def db(mock_supabase: respx.MockRouter):
    return {
        "view_head": mock_supabase.head(VIEW_URL).mock(side_effect=view_head),
        "collected": mock_supabase.head(CANDIDATES_URL).mock(
            return_value=httpx.Response(200, headers={"Content-Range": "0-6/7"})
        ),
        "recent": mock_supabase.get(VIEW_URL).mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "id": CID,
                        "title": "제목",
                        "growth_pct": 0.6,
                        "status_changed_at": "2026-11-16T03:00:00+00:00",
                        "rep_profile_id": P1,
                    },
                    {
                        "id": CID[:-1] + "2",
                        "title": "프로필 삭제됨",
                        "growth_pct": None,
                        "status_changed_at": "2026-11-15T03:00:00+00:00",
                        "rep_profile_id": None,
                    },
                ],
            )
        ),
        "profiles": mock_supabase.get(PROFILES_URL).mock(
            return_value=httpx.Response(200, json=[{"id": P1, "name": "한국 C.C"}])
        ),
    }


def test_summary_default_7d(client, db, headers):
    before = datetime.now(UTC)
    resp = client.get("/v1/dashboard/summary", headers=headers)
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["stats"] == {
        "collected": 7,
        "in_progress": None,
        "reviewed": None,
        "upload_pending": None,
    }
    assert body["stealth"] == {"producible": 3, "pending": 1}
    assert body["recent_ready"] == [
        {
            "id": CID,
            "title": "제목",
            "profile_name": "한국 C.C",
            "growth_pct": 0.6,
            "status_changed_at": "2026-11-16T03:00:00Z",
        },
        {
            "id": CID[:-1] + "2",
            "title": "프로필 삭제됨",
            "profile_name": None,
            "growth_pct": None,
            "status_changed_at": "2026-11-15T03:00:00Z",
        },
    ]

    since = datetime.fromisoformat(
        db["collected"].calls.last.request.url.params["created_at"].removeprefix("gte.")
    )
    assert abs((before - since) - timedelta(days=7)) < timedelta(seconds=5)

    rp = db["recent"].calls.last.request.url.params
    assert rp["display_status"] == "eq.producible"
    assert rp["order"] == "status_changed_at.desc,id.asc" and rp["limit"] == "5"
    assert rp["status_changed_at"].startswith("gte.")
    for route in db.values():
        for call in route.calls:
            assert call.request.url.params["workspace_id"] == f"eq.{WORKSPACE_ID}"
    # stealth는 기간 무관
    for call in db["view_head"].calls:
        assert "status_changed_at" not in call.request.url.params


def test_summary_24h(client, db, headers):
    before = datetime.now(UTC)
    assert client.get("/v1/dashboard/summary?period=24h", headers=headers).status_code == 200
    since = datetime.fromisoformat(
        db["collected"].calls.last.request.url.params["created_at"].removeprefix("gte.")
    )
    assert abs((before - since) - timedelta(hours=24)) < timedelta(seconds=5)


def test_summary_bad_period_400(client, headers):
    resp = client.get("/v1/dashboard/summary?period=30d", headers=headers)
    assert resp.status_code == 400 and resp.json()["field"] == "period"


@pytest.mark.parametrize("route", ["view_head", "collected", "recent", "profiles"])
def test_summary_db_error_503(client, db, headers, route):
    db[route].mock(return_value=httpx.Response(500))
    assert client.get("/v1/dashboard/summary", headers=headers).status_code == 503


def test_summary_requires_login(client):
    assert client.get("/v1/dashboard/summary").status_code == 401
