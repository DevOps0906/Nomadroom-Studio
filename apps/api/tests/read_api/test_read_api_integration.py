"""A-02·A-04·A-06 로컬 Supabase 통합 테스트(-m integration). 시드(supabase/seed.sql) 필요.

키는 셸 환경변수로만. 테스트 사용자를 시드 워크스페이스 구성원으로 넣고 끝나면 지운다.
"""

import os
import secrets
import uuid
from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.supabase import rest_url, service_headers
from tests.test_integration import admin, settings  # noqa: F401  (fixture 재사용)

pytestmark = pytest.mark.integration

SEED_WS = "00000000-0000-4000-8000-000000000001"
NO_PREV_ID = "00000000-0000-4000-8000-000000000203"


@pytest.fixture(scope="module")
def seed_token(settings: Settings, admin: httpx.Client) -> Iterator[str]:  # noqa: F811
    headers = service_headers(settings)
    email = f"it-read-{uuid.uuid4().hex[:12]}@example.test"
    password = secrets.token_urlsafe(24)
    r = admin.post(
        "/auth/v1/admin/users",
        headers=headers,
        json={"email": email, "password": password, "email_confirm": True},
    )
    assert r.status_code in (200, 201), r.status_code
    user_id = r.json()["id"]
    try:
        r = admin.post(
            rest_url(settings, "workspace_members"),
            headers=headers,
            json={"workspace_id": SEED_WS, "user_id": user_id},
        )
        assert r.status_code == 201, r.status_code
        r = admin.post(
            "/auth/v1/token",
            params={"grant_type": "password"},
            headers={"apikey": os.environ["SUPABASE_PUBLISHABLE_KEY"]},
            json={"email": email, "password": password},
        )
        assert r.status_code == 200, r.status_code
        yield r.json()["access_token"]
    finally:
        admin.delete(
            rest_url(settings, "workspace_members"),
            headers=headers,
            params={"user_id": f"eq.{user_id}"},
        )
        admin.delete(f"/auth/v1/admin/users/{user_id}", headers=headers)


@pytest.fixture(scope="module")
def other_candidate_id(settings: Settings, admin: httpx.Client) -> Iterator[str]:  # noqa: F811
    headers = service_headers(settings)
    ws_id, cid = str(uuid.uuid4()), str(uuid.uuid4())
    r = admin.post(
        rest_url(settings, "workspaces"), headers=headers, json={"id": ws_id, "name": "it-other"}
    )
    assert r.status_code == 201, r.status_code
    try:
        r = admin.post(
            rest_url(settings, "candidates"),
            headers=headers,
            json={"id": cid, "workspace_id": ws_id, "video_id": "it-v", "title": "it"},
        )
        assert r.status_code == 201, r.status_code
        yield cid
    finally:
        admin.delete(
            rest_url(settings, "workspaces"), headers=headers, params={"id": f"eq.{ws_id}"}
        )


@pytest.fixture(scope="module")
def api(settings: Settings) -> Iterator[TestClient]:  # noqa: F811
    with TestClient(create_app(settings)) as c:
        yield c


def test_seed_counts_and_evidence(api: TestClient, seed_token: str, other_candidate_id: str):
    h = {"Authorization": f"Bearer {seed_token}"}
    resp = api.get("/v1/candidates", headers=h)
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["counts"] == {"total": 5, "producible": 3, "pending": 1, "excluded": 0, "used": 1}
    assert len(body["items"]) == 5
    assert body["categories"] == sorted(body["categories"])
    by_id = {i["id"]: i for i in body["items"]}
    assert by_id[NO_PREV_ID]["status"] == "pending" and by_id[NO_PREV_ID]["prev"] is None
    assert by_id["00000000-0000-4000-8000-000000000205"]["status"] == "used"
    assert by_id["00000000-0000-4000-8000-000000000204"]["growth_pct"] == 12.5
    assert by_id["00000000-0000-4000-8000-000000000201"]["period_days"] == 7.0
    assert by_id["00000000-0000-4000-8000-000000000201"]["profile_names"] == ["한국 C.C 정체 후보"]

    growth = api.get("/v1/candidates?sort=growth&size=2", headers=h).json()["items"]
    assert [i["id"] for i in growth] == [
        "00000000-0000-4000-8000-000000000204",
        "00000000-0000-4000-8000-000000000201",  # 0.60 동률 → id asc
    ]

    # 프로필 102 판정이 있는 후보는 5건 전부(상태 무관), status 필터는 counts에 영향 없음
    p102 = api.get(
        "/v1/candidates",
        headers=h,
        params={"profile_id": "00000000-0000-4000-8000-000000000102", "status": "used"},
    ).json()
    assert p102["counts"]["total"] == 5 and len(p102["items"]) == 1

    # q 특수문자: 실제 PostgREST에서 400·503 없이 동작
    for q in [',()."\\*%_', "반전", 'a"b', "%", "_"]:
        r = api.get("/v1/candidates", headers=h, params={"q": q})
        assert r.status_code == 200, (q, r.json())
    hit = api.get("/v1/candidates", headers=h, params={"q": "반전"}).json()
    assert hit["counts"]["total"] == 2
    assert api.get("/v1/candidates", headers=h, params={"q": "%"}).json()["counts"]["total"] == 0

    ev = api.get(f"/v1/candidates/{NO_PREV_ID}/evidence", headers=h)
    assert ev.status_code == 200
    evb = ev.json()
    assert evb["needs_prev"] is True and evb["prev"] is None
    assert evb["curr"]["view_count"] == 270000 and evb["reason"] == "no_prev"
    assert evb["next_observation_at"] == "2026-11-17T03:00:00Z"

    other = api.get(f"/v1/candidates/{other_candidate_id}/evidence", headers=h)
    assert other.status_code == 404 and other.json()["code"] == "NOT_FOUND"

    summary = api.get("/v1/dashboard/summary", headers=h)
    assert summary.status_code == 200
    assert summary.json()["stealth"] == {"producible": 3, "pending": 1}
