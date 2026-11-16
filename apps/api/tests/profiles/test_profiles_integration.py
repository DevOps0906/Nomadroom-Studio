"""A-03 로컬 Supabase 통합 테스트(-m integration). 키는 셸 환경변수로만."""

import uuid
from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.supabase import rest_url, service_headers
from tests.test_integration import admin, settings, world  # noqa: F401  (fixture 재사용)

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def profile_ids(settings: Settings, admin: httpx.Client, world: dict) -> list[str]:  # noqa: F811
    ids = [str(uuid.uuid4()) for _ in range(2)]
    r = admin.post(
        rest_url(settings, "profiles"),
        headers=service_headers(settings),
        json=[
            {
                "id": i,
                "workspace_id": world["workspace_id"],
                "name": f"it-{n}",
                "market": "KR",
                "max_growth_pct": 10,
            }
            for n, i in enumerate(ids)
        ],
    )
    assert r.status_code == 201, r.status_code
    return ids  # 워크스페이스 삭제(cascade)로 정리


@pytest.fixture(scope="module")
def api(settings: Settings) -> Iterator[TestClient]:  # noqa: F811
    with TestClient(create_app(settings)) as c:
        yield c


def test_profiles_flow(api: TestClient, world: dict, profile_ids: list[str]):  # noqa: F811
    h = {"Authorization": f"Bearer {world['access_token']}"}
    resp = api.get("/v1/profiles", headers=h)
    assert resp.status_code == 200
    items = {p["id"]: p for p in resp.json()["items"]}
    assert set(items) == set(profile_ids)

    pid = profile_ids[0]
    body = {
        "market": "JP",
        "format": "short",
        "category": "전체",
        "min_views": 100,
        "max_growth_pct": 12.34,
        "keywords": ["라멘", "RAMEN", "ramen"],
        "cc_only": True,
        "include_broadcast": False,
        "updated_at": items[pid]["updated_at"],
    }
    first = api.put(f"/v1/profiles/{pid}", headers=h, json=body)
    assert first.status_code == 200, first.json()
    saved = first.json()
    assert saved["market"] == "JP" and saved["category"] is None
    assert saved["keywords"] == ["라멘", "RAMEN"] and saved["max_growth_pct"] == 12.34
    assert saved["updated_at"] != items[pid]["updated_at"]

    again = api.put(f"/v1/profiles/{pid}", headers=h, json=body)
    assert again.status_code == 409 and again.json()["code"] == "CONFLICT"

    # 새 updated_at으로는 다시 저장된다
    body["updated_at"] = saved["updated_at"]
    assert api.put(f"/v1/profiles/{pid}", headers=h, json=body).status_code == 200

    missing = api.put(f"/v1/profiles/{uuid.uuid4()}", headers=h, json=body)
    assert missing.status_code == 404

    sel = api.put("/v1/profiles/selection", headers=h, json={"selected_ids": profile_ids})
    assert sel.status_code == 200 and sel.json() == {"selected_ids": profile_ids}
    bad = api.put("/v1/profiles/selection", headers=h, json={"selected_ids": [str(uuid.uuid4())]})
    assert bad.status_code == 400 and bad.json()["field"] == "selected_ids"
    listed = api.get("/v1/profiles", headers=h).json()["items"]
    assert all(p["selected"] for p in listed)
    clear = api.put("/v1/profiles/selection", headers=h, json={"selected_ids": []})
    assert clear.status_code == 200
    assert not any(p["selected"] for p in api.get("/v1/profiles", headers=h).json()["items"])


@pytest.fixture(scope="module")
def other_profile_id(settings: Settings, admin: httpx.Client) -> Iterator[str]:  # noqa: F811
    """다른 워크스페이스에 실재하는 프로필(service 키로 만들고 끝나면 워크스페이스째 지운다)."""
    headers = service_headers(settings)
    ws_id, pid = str(uuid.uuid4()), str(uuid.uuid4())
    r = admin.post(
        rest_url(settings, "workspaces"), headers=headers, json={"id": ws_id, "name": "it-other"}
    )
    assert r.status_code == 201, r.status_code
    try:
        r = admin.post(
            rest_url(settings, "profiles"),
            headers=headers,
            json={
                "id": pid,
                "workspace_id": ws_id,
                "name": "it-other",
                "market": "KR",
                "max_growth_pct": 10,
            },
        )
        assert r.status_code == 201, r.status_code
        yield pid
    finally:
        admin.delete(
            rest_url(settings, "workspaces"), headers=headers, params={"id": f"eq.{ws_id}"}
        )


def test_other_workspace_profile_is_hidden(
    api: TestClient,
    world: dict,  # noqa: F811
    profile_ids: list[str],
    other_profile_id: str,
):
    h = {"Authorization": f"Bearer {world['access_token']}"}
    listed = api.get("/v1/profiles", headers=h).json()["items"]
    assert other_profile_id not in {p["id"] for p in listed}

    body = {
        "market": "KR",
        "format": "all",
        "category": None,
        "min_views": 0,
        "max_growth_pct": 1,
        "keywords": [],
        "cc_only": False,
        "include_broadcast": True,
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    put = api.put(f"/v1/profiles/{other_profile_id}", headers=h, json=body)
    assert put.status_code == 404 and put.json()["code"] == "NOT_FOUND"

    sel = api.put(
        "/v1/profiles/selection",
        headers=h,
        json={"selected_ids": [profile_ids[0], other_profile_id]},
    )
    assert sel.status_code == 400
    assert sel.json() == {
        "code": "VALIDATION",
        "message": "없는 프로필이 포함되어 있습니다.",
        "field": "selected_ids",
    }
