"""A-08 단위 테스트(PostgREST는 respx 가짜)."""

import json
from datetime import UTC, datetime

import httpx
import pytest

from tests.conftest import WORKSPACE_ID
from tests.used.conftest import REST

CANDIDATES_URL = f"{REST}/candidates"
CID = "00000000-0000-4000-8000-000000000201"
URL = f"/v1/candidates/{CID}/used"
USED_AT = "2026-11-10T01:02:03+00:00"
NOT_FOUND = {"code": "NOT_FOUND", "message": "찾을 수 없습니다."}
DB_ERROR = {"code": "UPSTREAM_ERROR", "message": "데이터 저장소 요청에 실패했습니다."}


def row(used: bool, used_at: str | None) -> dict:
    return {"id": CID, "used": used, "used_at": used_at}


def test_mark_used_sets_new_timestamp(client, mock_supabase, headers):
    route = mock_supabase.patch(CANDIDATES_URL).mock(
        side_effect=lambda req: httpx.Response(
            200, json=[row(True, json.loads(req.content)["used_at"])]
        )
    )
    before = datetime.now(UTC)
    resp = client.patch(URL, headers=headers, json={"used": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == CID and body["used"] is True
    assert datetime.fromisoformat(body["used_at"]) >= before
    req = route.calls.last.request
    p = req.url.params
    assert p["id"] == f"eq.{CID}" and p["workspace_id"] == f"eq.{WORKSPACE_ID}"
    assert p["used"] == "is.false"
    assert req.headers["Prefer"] == "return=representation"
    assert json.loads(req.content)["used"] is True


def test_mark_used_idempotent_keeps_used_at(client, mock_supabase, headers):
    mock_supabase.patch(CANDIDATES_URL).mock(return_value=httpx.Response(200, json=[]))
    get = mock_supabase.get(CANDIDATES_URL).mock(
        return_value=httpx.Response(200, json=[row(True, USED_AT)])
    )
    resp = client.patch(URL, headers=headers, json={"used": True})
    assert resp.status_code == 200
    assert resp.json() == {"id": CID, "used": True, "used_at": "2026-11-10T01:02:03Z"}
    p = get.calls.last.request.url.params
    assert p["id"] == f"eq.{CID}" and p["workspace_id"] == f"eq.{WORKSPACE_ID}"


def test_unmark_clears_used_at(client, mock_supabase, headers):
    route = mock_supabase.patch(CANDIDATES_URL).mock(
        return_value=httpx.Response(200, json=[row(False, None)])
    )
    resp = client.patch(URL, headers=headers, json={"used": False})
    assert resp.status_code == 200
    assert resp.json() == {"id": CID, "used": False, "used_at": None}
    req = route.calls.last.request
    assert "used" not in req.url.params
    assert req.url.params["workspace_id"] == f"eq.{WORKSPACE_ID}"
    assert json.loads(req.content) == {"used": False, "used_at": None}


def test_remark_after_unmark_gets_new_timestamp(client, mock_supabase, headers):
    state = {"used": True, "used_at": USED_AT}

    def patch(req: httpx.Request) -> httpx.Response:
        data = json.loads(req.content)
        if req.url.params.get("used") == "is.false" and state["used"]:
            return httpx.Response(200, json=[])
        state.update(data)
        return httpx.Response(200, json=[row(state["used"], state["used_at"])])

    mock_supabase.patch(CANDIDATES_URL).mock(side_effect=patch)
    mock_supabase.get(CANDIDATES_URL).mock(
        side_effect=lambda req: httpx.Response(200, json=[row(state["used"], state["used_at"])])
    )
    first = client.patch(URL, headers=headers, json={"used": True}).json()
    assert first["used_at"] == "2026-11-10T01:02:03Z"
    assert client.patch(URL, headers=headers, json={"used": False}).json()["used_at"] is None
    again = client.patch(URL, headers=headers, json={"used": True}).json()
    assert again["used"] is True
    assert datetime.fromisoformat(again["used_at"]) > datetime.fromisoformat(USED_AT)


@pytest.mark.parametrize("used", [True, False])
def test_missing_or_other_workspace_404(client, mock_supabase, headers, used):
    mock_supabase.patch(CANDIDATES_URL).mock(return_value=httpx.Response(200, json=[]))
    mock_supabase.get(CANDIDATES_URL).mock(return_value=httpx.Response(200, json=[]))
    resp = client.patch(URL, headers=headers, json={"used": used})
    assert resp.status_code == 404
    assert resp.json() == NOT_FOUND


@pytest.mark.parametrize(
    "payload",
    [{}, {"used": "true"}, {"used": 1}, {"used": None}, {"used": True, "extra": 1}],
)
def test_invalid_body_400(client, mock_supabase, headers, payload):
    # 앱 공통 검증 오류 처리기가 RequestValidationError를 400 VALIDATION으로 바꾼다
    route = mock_supabase.patch(CANDIDATES_URL)
    resp = client.patch(URL, headers=headers, json=payload)
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == "VALIDATION" and body["message"] == "입력값이 올바르지 않습니다."
    assert not route.called


def test_invalid_id_400(client, headers):
    resp = client.patch("/v1/candidates/not-a-uuid/used", headers=headers, json={"used": True})
    assert resp.status_code == 400


def test_requires_login(client):
    resp = client.patch(URL, json={"used": True})
    assert resp.status_code == 401


def test_db_error_503(client, mock_supabase, headers):
    mock_supabase.patch(CANDIDATES_URL).mock(return_value=httpx.Response(500, json={}))
    resp = client.patch(URL, headers=headers, json={"used": False})
    assert resp.status_code == 503
    assert resp.json() == DB_ERROR
