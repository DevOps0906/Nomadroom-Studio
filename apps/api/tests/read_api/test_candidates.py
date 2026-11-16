"""A-04 · A-06 단위 테스트(PostgREST는 respx 가짜)."""

import uuid
from typing import Any

import httpx
import pytest
import respx

from app.routes.candidates import _like_pattern
from tests.conftest import WORKSPACE_ID
from tests.read_api.conftest import REST

VIEW_URL = f"{REST}/candidate_list_v"
CANDIDATES_URL = f"{REST}/candidates"
PROFILES_URL = f"{REST}/profiles"
VERDICTS_URL = f"{REST}/candidate_verdicts"
CID = "00000000-0000-4000-8000-000000000201"
CID2 = "00000000-0000-4000-8000-000000000203"
P1 = "00000000-0000-4000-8000-000000000101"
P2 = "00000000-0000-4000-8000-000000000102"
COUNTS = {"producible": 3, "pending": 1, "excluded": 0, "used": 1}
DB_ERROR = {"code": "UPSTREAM_ERROR", "message": "데이터 저장소 요청에 실패했습니다."}


def item_row(**overrides: Any) -> dict:
    base = {
        "id": CID,
        "thumbnail_url": "https://i.ytimg.com/vi/x/hqdefault.jpg",
        "display_status": "producible",
        "genre": "예능",
        "title": "제목",
        "format": "long",
        "license_cc": True,
        "used": False,
        "growth_pct": 0.6,
        "prev_observed_at": "2026-11-09T03:00:00+00:00",
        "prev_view_count": 450000,
        "curr_observed_at": "2026-11-16T03:00:00+00:00",
        "curr_view_count": 452700,
        "latest_observed_at": "2026-11-16T03:00:00+00:00",
    }
    base.update(overrides)
    return base


def head_count(request: httpx.Request) -> httpx.Response:
    status = request.url.params["display_status"].removeprefix("eq.")
    n = COUNTS[status]
    rng = f"0-{n - 1}/{n}" if n else "*/0"
    return httpx.Response(200, headers={"Content-Range": rng})


@pytest.fixture
def db(mock_supabase: respx.MockRouter):
    """목록 요청에 쓰는 PostgREST 경로 전부를 가짜로 둔다. 각 route를 돌려준다."""
    routes = {
        "head": mock_supabase.head(VIEW_URL).mock(side_effect=head_count),
        "items": mock_supabase.get(VIEW_URL).mock(
            return_value=httpx.Response(200, json=[item_row()])
        ),
        "categories": mock_supabase.get(CANDIDATES_URL).mock(
            return_value=httpx.Response(
                200,
                json=[
                    {"category": "예능"},
                    {"category": "스포츠"},
                    {"category": "예능"},
                    {"category": "가요"},
                ],
            )
        ),
        "profiles": mock_supabase.get(PROFILES_URL).mock(
            return_value=httpx.Response(
                200, json=[{"id": P1, "name": "한국"}, {"id": P2, "name": "가나 일본"}]
            )
        ),
        "verdicts": mock_supabase.get(VERDICTS_URL).mock(
            return_value=httpx.Response(
                200,
                json=[
                    {"candidate_id": CID, "profile_id": P1},
                    {"candidate_id": CID, "profile_id": P2},
                ],
            )
        ),
    }
    return routes


def params_of(route) -> list[httpx.QueryParams]:
    return [c.request.url.params for c in route.calls]


# --- A-04 ----------------------------------------------------------------------


def test_list_default(client, db, headers):
    resp = client.get("/v1/candidates", headers=headers)
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["counts"] == {"total": 5, **COUNTS}
    assert body["counts"]["total"] == sum(COUNTS.values())
    assert body["categories"] == ["가요", "스포츠", "예능"]
    item = body["items"][0]
    assert item["status"] == "producible"
    assert item["profile_names"] == ["가나 일본", "한국"]
    assert item["prev"] == {"observed_at": "2026-11-09T03:00:00Z", "view_count": 450000}
    assert item["period_days"] == 7.0 and item["growth_pct"] == 0.6
    assert item["next_observation_at"] is None

    p = db["items"].calls.last.request.url.params
    assert p["workspace_id"] == f"eq.{WORKSPACE_ID}"
    assert p["order"] == "created_at.desc,id.asc"
    assert p["limit"] == "24" and p["offset"] == "0"
    assert "display_status" not in p
    for hp in params_of(db["head"]):
        assert hp["workspace_id"] == f"eq.{WORKSPACE_ID}"
    assert db["head"].calls.last.request.headers["prefer"] == "count=exact"
    for route in ("categories", "profiles", "verdicts"):
        assert db[route].calls.last.request.url.params["workspace_id"] == f"eq.{WORKSPACE_ID}"
    assert db["verdicts"].calls.last.request.url.params["status"] == "neq.excluded"


@pytest.mark.parametrize(
    ("sort", "order"),
    [
        ("growth", "growth_pct.desc.nullslast,id.asc"),
        ("views", "curr_view_count.desc.nullslast,id.asc"),
        ("recent", "created_at.desc,id.asc"),
    ],
)
def test_sort_tie_breaker(client, db, headers, sort, order):
    assert client.get(f"/v1/candidates?sort={sort}", headers=headers).status_code == 200
    assert db["items"].calls.last.request.url.params["order"] == order


def test_filters_applied_to_items_and_counts(client, db, headers):
    pid = uuid.UUID(P1)
    resp = client.get(
        "/v1/candidates",
        headers=headers,
        params={
            "status": "pending",
            "category": " 예능 ",
            "format": "long",
            "profile_id": str(pid),
            "license": "cc",
            "page": 3,
            "size": 10,
        },
    )
    assert resp.status_code == 200, resp.json()
    p = db["items"].calls.last.request.url.params
    assert p["display_status"] == "eq.pending"
    assert p["limit"] == "10" and p["offset"] == "20"
    heads = params_of(db["head"])
    assert sorted(h["display_status"] for h in heads) == [
        "eq.excluded",
        "eq.pending",
        "eq.producible",
        "eq.used",
    ]
    for q in [p, *heads]:
        assert q["category"] == "eq.예능"
        assert q["format"] == "eq.long"
        assert q["license_cc"] == "is.true"
        assert q["candidate_verdicts.profile_id"] == f"eq.{pid}"
        assert q["candidate_verdicts.workspace_id"] == f"eq.{WORKSPACE_ID}"
        assert "candidate_verdicts!inner(profile_id)" in q["select"]
    # counts는 status 필터를 쓰지 않는다(상태별 HEAD만)
    assert resp.json()["counts"]["total"] == 5


def test_status_all_format_all_license_any_no_filter(client, db, headers):
    resp = client.get("/v1/candidates?status=all&format=all&license=any", headers=headers)
    assert resp.status_code == 200
    p = db["items"].calls.last.request.url.params
    for key in ("display_status", "format", "license_cc", "category", "or"):
        assert key not in p


@pytest.mark.parametrize(
    ("query", "field"),
    [
        ("size=61", "size"),
        ("size=0", "size"),
        ("page=0", "page"),
        ("page=1001", "page"),
        ("status=bad", "status"),
        ("sort=bad", "sort"),
        ("license=all", "license"),
        ("profile_id=x", "profile_id"),
        ("q=" + "a" * 101, "q"),
        ("q=%20%0A", "q"),
        ("q=a%01b", "q"),
        ("q=a%0Ab", "q"),
        ("category=" + "a" * 41, "category"),
        ("category=a%7Fb", "category"),
    ],
)
def test_validation_400(client, db, headers, query, field):
    resp = client.get(f"/v1/candidates?{query}", headers=headers)
    assert resp.status_code == 400
    assert resp.json()["code"] == "VALIDATION" and resp.json()["field"] == field
    assert not db["items"].called


def test_size_60_ok_and_q_boundary(client, db, headers):
    resp = client.get("/v1/candidates", headers=headers, params={"size": 60, "q": "a" * 100})
    assert resp.status_code == 200
    assert db["items"].calls.last.request.url.params["limit"] == "60"


def test_page_1000_ok(client, db, headers):
    resp = client.get("/v1/candidates", headers=headers, params={"page": 1000, "size": 60})
    assert resp.status_code == 200
    assert db["items"].calls.last.request.url.params["offset"] == str(999 * 60)


@pytest.mark.parametrize("q", ["", "   "])
def test_blank_q_no_filter(client, db, headers, q):
    resp = client.get("/v1/candidates", headers=headers, params={"q": q})
    assert resp.status_code == 200
    for p in [db["items"].calls.last.request.url.params, *params_of(db["head"])]:
        assert "or" not in p


def test_q_special_chars_escaped(client, db, headers):
    q = ' a,b().c"d\\e*f%g_h '
    resp = client.get("/v1/candidates", headers=headers, params={"q": q})
    assert resp.status_code == 200
    expected = '"*a,b().c\\"d\\\\\\\\e_f\\\\%g\\\\_h*"'
    for p in [db["items"].calls.last.request.url.params, *params_of(db["head"])]:
        assert p["or"] == f"(title.ilike.{expected},channel_title.ilike.{expected})"


@pytest.mark.parametrize(
    ("q", "pattern"),
    [
        ("abc", '"*abc*"'),
        ("a%b", '"*a\\\\%b*"'),
        ("a_b", '"*a\\\\_b*"'),
        ("a*b", '"*a_b*"'),
        ('a"b', '"*a\\"b*"'),
        ("a\\b", '"*a\\\\\\\\b*"'),
        ("a,b)", '"*a,b)*"'),
    ],
)
def test_like_pattern(q, pattern):
    assert _like_pattern(q) == pattern


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://i.ytimg.com/vi/x/hqdefault.jpg", "https://i.ytimg.com/vi/x/hqdefault.jpg"),
        ("http://i.ytimg.com/vi/x.jpg", None),
        ("https://i.ytimg.com.evil.test/x.jpg", None),
        ("https://evil.test/https://i.ytimg.com/", None),
        ("javascript:alert(1)", None),
        ("https://i.ytimg.com@evil.com/", None),
        ("https://i.ytimg.com:8443/", None),
        ("https://I.YTIMG.COM/", None),
        ("https://i.ytimg.com/vi/x/hq.jpg", "https://i.ytimg.com/vi/x/hq.jpg"),
        (None, None),
    ],
)
def test_thumbnail_allowlist(client, db, headers, url, expected):
    db["items"].mock(return_value=httpx.Response(200, json=[item_row(thumbnail_url=url)]))
    resp = client.get("/v1/candidates", headers=headers)
    assert resp.json()["items"][0]["thumbnail_url"] == expected


def test_pending_needs_prev_item(client, db, headers):
    row = item_row(
        id=CID2,
        display_status="pending",
        growth_pct=None,
        prev_observed_at=None,
        prev_view_count=None,
        latest_observed_at="2026-11-16T03:00:00.5+00:00",
    )
    db["items"].mock(return_value=httpx.Response(200, json=[row]))
    db["verdicts"].mock(return_value=httpx.Response(200, json=[]))
    item = client.get("/v1/candidates", headers=headers).json()["items"][0]
    assert item["prev"] is None and item["period_days"] is None and item["growth_pct"] is None
    assert item["next_observation_at"] == "2026-11-17T03:00:00.500000Z"
    assert item["profile_names"] == []


def test_period_days_round_half_up(client, db, headers):
    # 6.25일 → 6.3(ROUND_HALF_UP)
    row = item_row(
        prev_observed_at="2026-11-10T03:00:00+00:00", curr_observed_at="2026-11-16T09:00:00+00:00"
    )
    db["items"].mock(return_value=httpx.Response(200, json=[row]))
    assert client.get("/v1/candidates", headers=headers).json()["items"][0]["period_days"] == 6.3


def test_empty_page_skips_verdicts(client, db, headers):
    db["items"].mock(return_value=httpx.Response(200, json=[]))
    resp = client.get("/v1/candidates?page=99", headers=headers)
    assert resp.status_code == 200 and resp.json()["items"] == []
    assert not db["verdicts"].called


@pytest.mark.parametrize("route", ["items", "head", "categories", "profiles", "verdicts"])
def test_list_db_error_503(client, db, headers, route):
    db[route].mock(return_value=httpx.Response(400, json={"code": "PGRST100"}))
    resp = client.get("/v1/candidates", headers=headers)
    assert resp.status_code == 503 and resp.json() == DB_ERROR


def test_bad_content_range_503(client, db, headers):
    db["head"].mock(return_value=httpx.Response(200, headers={"Content-Range": "0-1/*"}))
    assert client.get("/v1/candidates", headers=headers).status_code == 503


def test_list_requires_login(client):
    assert client.get("/v1/candidates").status_code == 401


# --- A-06 ----------------------------------------------------------------------


def evidence_row(**overrides: Any) -> dict:
    base = {
        "id": CID,
        "title": "제목",
        "display_status": "producible",
        "growth_pct": 0.6,
        "reason": None,
        "prev_observed_at": "2026-11-09T03:00:00+00:00",
        "prev_view_count": 450000,
        "curr_observed_at": "2026-11-16T03:00:00+00:00",
        "curr_view_count": 452700,
        "latest_observed_at": "2026-11-16T03:00:00+00:00",
    }
    base.update(overrides)
    return base


def test_evidence_ok(client, mock_supabase, headers):
    route = mock_supabase.get(VIEW_URL).mock(
        return_value=httpx.Response(200, json=[evidence_row()])
    )
    resp = client.get(f"/v1/candidates/{CID}/evidence", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {
        "candidate": {"id": CID, "title": "제목", "status": "producible"},
        "prev": {"observed_at": "2026-11-09T03:00:00Z", "view_count": 450000},
        "curr": {"observed_at": "2026-11-16T03:00:00Z", "view_count": 452700},
        "growth_pct": 0.6,
        "reason": None,
        "needs_prev": False,
        "next_observation_at": None,
    }
    p = route.calls.last.request.url.params
    assert p["id"] == f"eq.{CID}" and p["workspace_id"] == f"eq.{WORKSPACE_ID}"


def test_evidence_needs_prev(client, mock_supabase, headers):
    row = evidence_row(
        display_status="pending",
        growth_pct=None,
        reason="no_prev",
        prev_observed_at=None,
        prev_view_count=None,
    )
    mock_supabase.get(VIEW_URL).mock(return_value=httpx.Response(200, json=[row]))
    body = client.get(f"/v1/candidates/{CID}/evidence", headers=headers).json()
    assert body["needs_prev"] is True and body["prev"] is None
    assert body["curr"]["view_count"] == 452700 and body["reason"] == "no_prev"
    assert body["next_observation_at"] == "2026-11-17T03:00:00Z"


def test_evidence_no_rep_verdict(client, mock_supabase, headers):
    row = evidence_row(
        display_status="pending",
        growth_pct=None,
        reason=None,
        prev_observed_at=None,
        prev_view_count=None,
        curr_observed_at=None,
        curr_view_count=None,
        latest_observed_at=None,
    )
    mock_supabase.get(VIEW_URL).mock(return_value=httpx.Response(200, json=[row]))
    resp = client.get(f"/v1/candidates/{CID}/evidence", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["prev"] is None and body["curr"] is None and body["reason"] is None
    assert body["needs_prev"] is True and body["next_observation_at"] is None


def test_evidence_curr_cleaned_hides_prev_and_reason(client, mock_supabase, headers):
    row = evidence_row(reason="growth_out_of_range", curr_observed_at=None, curr_view_count=None)
    mock_supabase.get(VIEW_URL).mock(return_value=httpx.Response(200, json=[row]))
    body = client.get(f"/v1/candidates/{CID}/evidence", headers=headers).json()
    assert body["prev"] is None and body["reason"] is None and body["growth_pct"] is None
    assert body["needs_prev"] is True


def test_evidence_other_workspace_404(client, mock_supabase, headers):
    """타 워크스페이스 행은 workspace_id 조건으로 0행 → 404(존재 노출 없음)."""
    mock_supabase.get(VIEW_URL).mock(return_value=httpx.Response(200, json=[]))
    resp = client.get(f"/v1/candidates/{uuid.uuid4()}/evidence", headers=headers)
    assert resp.status_code == 404 and resp.json()["code"] == "NOT_FOUND"


def test_evidence_bad_id_400(client, headers):
    assert client.get("/v1/candidates/not-a-uuid/evidence", headers=headers).status_code == 400


def test_evidence_db_error_503(client, mock_supabase, headers):
    mock_supabase.get(VIEW_URL).mock(side_effect=httpx.ConnectError("boom"))
    resp = client.get(f"/v1/candidates/{CID}/evidence", headers=headers)
    assert resp.status_code == 503 and resp.json() == DB_ERROR


def test_evidence_requires_login(client):
    assert client.get(f"/v1/candidates/{CID}/evidence").status_code == 401
