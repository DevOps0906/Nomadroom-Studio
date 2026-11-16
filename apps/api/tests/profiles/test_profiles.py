import json
import uuid
from typing import Any

import httpx
import pytest
import respx

from tests.conftest import JWKS_URL, SUPABASE_URL, WORKSPACE_ID

MEMBERS_URL = f"{SUPABASE_URL}/rest/v1/workspace_members"
PROFILES_URL = f"{SUPABASE_URL}/rest/v1/profiles"
RPC_URL = f"{SUPABASE_URL}/rest/v1/rpc/set_profile_selection"
PROFILE_ID = uuid.UUID("aaaaaaaa-0000-4000-8000-000000000010")
OTHER_PROFILE_ID = uuid.UUID("bbbbbbbb-0000-4000-8000-000000000010")
UPDATED_AT = "2026-11-16T01:02:03.123456+00:00"
DB_ERROR = {"code": "UPSTREAM_ERROR", "message": "데이터 저장소 요청에 실패했습니다."}


@pytest.fixture(autouse=True)
def auth_routes(mock_supabase: respx.MockRouter, jwks_payload: dict) -> None:
    mock_supabase.get(JWKS_URL).mock(return_value=httpx.Response(200, json=jwks_payload))
    mock_supabase.get(MEMBERS_URL).mock(
        return_value=httpx.Response(200, json=[{"workspace_id": str(WORKSPACE_ID)}])
    )


@pytest.fixture
def headers(make_token) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token()}"}


def row(**overrides: Any) -> dict:
    base = {
        "id": str(PROFILE_ID),
        "name": "기본",
        "market": "KR",
        "format": "all",
        "category": None,
        "min_views": 1000,
        "max_growth_pct": 12.5,
        "keywords": ["요리"],
        "cc_only": False,
        "include_broadcast": True,
        "selected": True,
        "updated_at": UPDATED_AT,
    }
    base.update(overrides)
    return base


def body(**overrides: Any) -> dict:
    base = {
        "market": "JP",
        "format": "short",
        "category": " 음식 ",
        "min_views": 5000,
        "max_growth_pct": 30.25,
        "keywords": [" 라멘 ", "라멘", "Ramen", "RAMEN"],
        "cc_only": True,
        "include_broadcast": False,
        "updated_at": UPDATED_AT,
    }
    base.update(overrides)
    return base


# --- GET -------------------------------------------------------------------


def test_list_profiles(client, mock_supabase, headers):
    route = mock_supabase.get(PROFILES_URL).mock(return_value=httpx.Response(200, json=[row()]))
    resp = client.get("/v1/profiles", headers=headers)
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["id"] == str(PROFILE_ID) and item["max_growth_pct"] == 12.5
    assert route.calls.last.request.url.params["workspace_id"] == f"eq.{WORKSPACE_ID}"


def test_list_requires_login(client):
    assert client.get("/v1/profiles").status_code == 401


@pytest.mark.parametrize("status", [400, 401, 500])
def test_list_db_error_503(client, mock_supabase, headers, status):
    mock_supabase.get(PROFILES_URL).mock(return_value=httpx.Response(status, json={"x": 1}))
    resp = client.get("/v1/profiles", headers=headers)
    assert resp.status_code == 503 and resp.json() == DB_ERROR


def test_list_db_connect_error_503(client, mock_supabase, headers):
    mock_supabase.get(PROFILES_URL).mock(side_effect=httpx.ConnectError("boom"))
    resp = client.get("/v1/profiles", headers=headers)
    assert resp.status_code == 503 and resp.json() == DB_ERROR


# --- PUT /{id} ---------------------------------------------------------------


def test_put_profile_ok(client, mock_supabase, headers):
    route = mock_supabase.patch(PROFILES_URL).mock(
        return_value=httpx.Response(200, json=[row(market="JP")])
    )
    resp = client.put(f"/v1/profiles/{PROFILE_ID}", headers=headers, json=body())
    assert resp.status_code == 200
    assert resp.json()["market"] == "JP"
    req = route.calls.last.request
    params = req.url.params
    assert params["id"] == f"eq.{PROFILE_ID}"
    assert params["workspace_id"] == f"eq.{WORKSPACE_ID}"
    # 마이크로초·오프셋 보존, '+'·':'는 퍼센트 인코딩(httpx params)
    assert params["updated_at"] == f"eq.{UPDATED_AT}"
    assert "updated_at=eq.2026-11-16T01%3A02%3A03.123456%2B00%3A00" in str(req.url)
    sent = json.loads(req.content)
    assert sent["category"] == "음식"
    assert sent["keywords"] == ["라멘", "Ramen"]
    assert sent["max_growth_pct"] == "30.25"
    assert sent["updated_at"] != UPDATED_AT and "+00:00" in sent["updated_at"]
    assert "name" not in sent and "selected" not in sent and "workspace_id" not in sent
    assert req.headers["prefer"] == "return=representation"


@pytest.mark.parametrize("category", ["", "  ", "전체", " 전체 ", None])
def test_category_empty_is_null(client, mock_supabase, headers, category):
    route = mock_supabase.patch(PROFILES_URL).mock(return_value=httpx.Response(200, json=[row()]))
    resp = client.put(f"/v1/profiles/{PROFILE_ID}", headers=headers, json=body(category=category))
    assert resp.status_code == 200
    assert json.loads(route.calls.last.request.content)["category"] is None


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"min_views": -1}, "min_views"),
        ({"min_views": 2_000_000_001}, "min_views"),
        ({"max_growth_pct": 1001}, "max_growth_pct"),
        ({"max_growth_pct": -0.01}, "max_growth_pct"),
        ({"max_growth_pct": 1.234}, "max_growth_pct"),
        ({"keywords": ["a", "b", "c", "d", "e", "f"]}, "keywords"),
        ({"keywords": ["a", " "]}, "keywords.1"),
        ({"keywords": ["x" * 31]}, "keywords.0"),
        ({"category": "가" * 41}, "category"),
        ({"market": "US"}, "market"),
        ({"format": "mid"}, "format"),
        ({"name": "새 이름"}, "name"),
        ({"selected": True}, "selected"),
        ({"updated_at": "2026-11-16T01:02:03.123456"}, "updated_at"),
        ({"updated_at": 1_700_000_000}, "updated_at"),
        # 제어 문자(\x00-\x1f, \x7f)
        ({"keywords": ["라\x00멘"]}, "keywords.0"),
        ({"keywords": ["a", "\tb"]}, "keywords.1"),
        ({"keywords": ["a\x7f"]}, "keywords.0"),
        ({"category": "음\n식"}, "category"),
        ({"category": "음식\x1f"}, "category"),
        # 원본 길이 상한(중복 제거·공백 제거 전)
        ({"keywords": ["a"] * 21}, "keywords"),
        ({"keywords": [" " * 195 + "abcdef"]}, "keywords.0"),
        ({"category": " " * 199 + "가나"}, "category"),
    ],
)
def test_put_profile_validation_400(client, mock_supabase, headers, overrides, field):
    route = mock_supabase.patch(PROFILES_URL)
    resp = client.put(f"/v1/profiles/{PROFILE_ID}", headers=headers, json=body(**overrides))
    assert resp.status_code == 400
    assert resp.json()["code"] == "VALIDATION"
    assert resp.json().get("field") == field
    assert route.call_count == 0


def test_put_profile_missing_updated_at_400(client, headers):
    b = body()
    del b["updated_at"]
    resp = client.put(f"/v1/profiles/{PROFILE_ID}", headers=headers, json=b)
    assert resp.status_code == 400


def test_put_profile_raw_limits_boundary_ok(client, mock_supabase, headers):
    """원본 20개·200자는 허용(중복 제거·공백 제거 뒤 규칙 통과)."""
    route = mock_supabase.patch(PROFILES_URL).mock(return_value=httpx.Response(200, json=[row()]))
    payload = body(keywords=["a"] * 20, category=" " * 198 + "음식")
    payload["keywords"][0] = " " * 199 + "a"
    resp = client.put(f"/v1/profiles/{PROFILE_ID}", headers=headers, json=payload)
    assert resp.status_code == 200
    sent = json.loads(route.calls.last.request.content)
    assert sent["keywords"] == ["a"] and sent["category"] == "음식"


def test_put_profile_keywords_dedupe_to_five_ok(client, mock_supabase, headers):
    route = mock_supabase.patch(PROFILES_URL).mock(return_value=httpx.Response(200, json=[row()]))
    kws = ["a", "b", "c", "d", "e", "A"]
    resp = client.put(f"/v1/profiles/{PROFILE_ID}", headers=headers, json=body(keywords=kws))
    assert resp.status_code == 200
    assert json.loads(route.calls.last.request.content)["keywords"] == ["a", "b", "c", "d", "e"]


def test_put_profile_twice_second_409(client, mock_supabase, headers):
    """같은 updated_at으로 두 번 PUT: 첫 번째 갱신 후 두 번째는 0행 → 존재 확인 → 409."""
    patch = mock_supabase.patch(PROFILES_URL).mock(
        side_effect=[
            httpx.Response(200, json=[row(updated_at="2026-11-16T02:00:00.654321+00:00")]),
            httpx.Response(200, json=[]),
        ]
    )
    exists = mock_supabase.get(PROFILES_URL).mock(
        return_value=httpx.Response(200, json=[{"id": str(PROFILE_ID)}])
    )
    first = client.put(f"/v1/profiles/{PROFILE_ID}", headers=headers, json=body())
    assert first.status_code == 200
    assert first.json()["updated_at"] == "2026-11-16T02:00:00.654321Z"
    second = client.put(f"/v1/profiles/{PROFILE_ID}", headers=headers, json=body())
    assert second.status_code == 409
    assert second.json()["code"] == "CONFLICT"
    assert patch.call_count == 2
    params = exists.calls.last.request.url.params
    assert params["workspace_id"] == f"eq.{WORKSPACE_ID}" and params["id"] == f"eq.{PROFILE_ID}"


def test_put_other_workspace_404(client, mock_supabase, headers):
    """타 워크스페이스 id + 틀린 updated_at: 워크스페이스로 한정한 재조회가 0행 → 404."""
    mock_supabase.patch(PROFILES_URL).mock(return_value=httpx.Response(200, json=[]))
    exists = mock_supabase.get(PROFILES_URL).mock(return_value=httpx.Response(200, json=[]))
    resp = client.put(
        f"/v1/profiles/{OTHER_PROFILE_ID}",
        headers=headers,
        json=body(updated_at="2000-01-01T00:00:00Z"),
    )
    assert resp.status_code == 404 and resp.json()["code"] == "NOT_FOUND"
    assert exists.calls.last.request.url.params["workspace_id"] == f"eq.{WORKSPACE_ID}"


@pytest.mark.parametrize("status", [400, 409, 500])
def test_put_profile_db_error_503(client, mock_supabase, headers, status):
    mock_supabase.patch(PROFILES_URL).mock(return_value=httpx.Response(status, json={}))
    resp = client.put(f"/v1/profiles/{PROFILE_ID}", headers=headers, json=body())
    assert resp.status_code == 503 and resp.json() == DB_ERROR


# --- PUT /selection ----------------------------------------------------------


def _ids(n: int) -> list[str]:
    return [str(uuid.UUID(int=i + 1)) for i in range(n)]


def test_selection_ok_dedupes(client, mock_supabase, headers):
    ids = _ids(2)
    route = mock_supabase.post(RPC_URL).mock(return_value=httpx.Response(200, json=ids))
    resp = client.put(
        "/v1/profiles/selection", headers=headers, json={"selected_ids": [ids[0], ids[1], ids[0]]}
    )
    assert resp.status_code == 200
    assert resp.json() == {"selected_ids": ids}
    sent = json.loads(route.calls.last.request.content)
    assert sent == {"p_workspace": str(WORKSPACE_ID), "p_ids": ids}


def test_selection_twenty_duplicates_ok(client, mock_supabase, headers):
    """원본 20개는 허용, 중복 제거 후 1개로 RPC 호출."""
    route = mock_supabase.post(RPC_URL).mock(
        return_value=httpx.Response(200, json=[str(PROFILE_ID)])
    )
    resp = client.put(
        "/v1/profiles/selection", headers=headers, json={"selected_ids": [str(PROFILE_ID)] * 20}
    )
    assert resp.status_code == 200
    assert json.loads(route.calls.last.request.content)["p_ids"] == [str(PROFILE_ID)]


def test_selection_empty_ok(client, mock_supabase, headers):
    mock_supabase.post(RPC_URL).mock(return_value=httpx.Response(200, json=[]))
    resp = client.put("/v1/profiles/selection", headers=headers, json={"selected_ids": []})
    assert resp.status_code == 200 and resp.json() == {"selected_ids": []}


@pytest.mark.parametrize(
    "payload",
    [
        {"selected_ids": _ids(4)},
        {"selected_ids": ["not-a-uuid"]},
        {"selected_ids": _ids(1), "extra": 1},
        {},
        {"selected_ids": [str(PROFILE_ID)] * 21},  # 원본 21개(중복 제거 전)
    ],
)
def test_selection_validation_400(client, mock_supabase, headers, payload):
    route = mock_supabase.post(RPC_URL)
    resp = client.put("/v1/profiles/selection", headers=headers, json=payload)
    assert resp.status_code == 400 and resp.json()["code"] == "VALIDATION"
    assert route.call_count == 0


@pytest.mark.parametrize(
    ("sqlstate", "message"),
    [
        ("NR001", "프로필은 최대 3개까지 선택할 수 있습니다."),
        ("NR002", "없는 프로필이 포함되어 있습니다."),
    ],
)
def test_selection_rpc_business_error_400(client, mock_supabase, headers, sqlstate, message):
    mock_supabase.post(RPC_URL).mock(
        return_value=httpx.Response(400, json={"code": sqlstate, "message": "x", "details": None})
    )
    resp = client.put("/v1/profiles/selection", headers=headers, json={"selected_ids": _ids(1)})
    assert resp.status_code == 400
    assert resp.json() == {"code": "VALIDATION", "message": message, "field": "selected_ids"}


@pytest.mark.parametrize(
    ("status", "payload"), [(400, {"code": "22P02"}), (404, {"code": "PGRST202"}), (500, {})]
)
def test_selection_other_db_error_503(client, mock_supabase, headers, status, payload):
    mock_supabase.post(RPC_URL).mock(return_value=httpx.Response(status, json=payload))
    resp = client.put("/v1/profiles/selection", headers=headers, json={"selected_ids": _ids(1)})
    assert resp.status_code == 503 and resp.json() == DB_ERROR


def test_selection_requires_login(client):
    assert client.put("/v1/profiles/selection", json={"selected_ids": []}).status_code == 401
