"""A-07 로컬 Supabase 통합 테스트(-m integration). YouTube만 respx 목, DB는 실제 로컬.

키는 셸 환경변수로만(SUPABASE_URL · SUPABASE_SERVICE_ROLE_KEY · SUPABASE_PUBLISHABLE_KEY).
시드 후보는 관측이 최근(24시간 미만)이라 건너뛰므로,
시드 값을 본뜬 후보를 테스트 워크스페이스에 넣는다.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import Settings
from app.main import create_app
from app.supabase import rest_url, service_headers
from app.youtube.client import VIDEOS_URL
from tests.test_integration import admin, settings, world  # noqa: F401  (fixture 재사용)
from tests.youtube.conftest import CHANNEL_X, YT_KEY, yt_item

pytestmark = pytest.mark.integration

VID_CC = "itVidCC0001"  # 시드 demo-video-01 본뜸: KR·C.C, 이전 관측 2일 전
VID_UNKNOWN = "itVidUNK002"  # 시드 demo-video-03 본뜸: 라이선스 미확인, 관측 없음
VID_GONE = "itVidGONE03"  # YouTube 응답에서 빠짐(삭제·비공개)


@pytest.fixture(scope="module")
def seeded(settings: Settings, admin: httpx.Client, world: dict) -> dict:  # noqa: F811
    ws = world["workspace_id"]
    h = {**service_headers(settings), "Prefer": "return=representation"}
    profile_id = str(uuid.uuid4())
    r = admin.post(
        rest_url(settings, "profiles"),
        headers=h,
        json={
            "id": profile_id,
            "workspace_id": ws,
            "name": "한국 C.C 정체 후보",
            "market": "KR",
            "min_views": 100000,
            "max_growth_pct": 5,
            "cc_only": True,
            "selected": True,
        },
    )
    assert r.status_code == 201, r.status_code
    cands = {vid: str(uuid.uuid4()) for vid in (VID_CC, VID_UNKNOWN, VID_GONE)}
    r = admin.post(
        rest_url(settings, "candidates"),
        headers=h,
        json=[
            {
                "id": cid,
                "workspace_id": ws,
                "video_id": vid,
                "title": f"통합 {vid}",
                "format": "long",
                "market": "KR",
                "license_cc": None,
                "rep_status": "pending",
                "rep_profile_id": profile_id,
            }
            for vid, cid in cands.items()
        ],
    )
    assert r.status_code == 201, r.status_code
    prev_id = str(uuid.uuid4())
    r = admin.post(
        rest_url(settings, "observations"),
        headers=h,
        json={
            "id": prev_id,
            "workspace_id": ws,
            "candidate_id": cands[VID_CC],
            "observed_at": (datetime.now(UTC) - timedelta(days=2)).isoformat(),
            "view_count": 450000,
        },
    )
    assert r.status_code == 201, r.status_code
    return {"profile_id": profile_id, "cands": cands, "prev_id": prev_id}


@pytest.fixture(scope="module")
def api(settings: Settings) -> Iterator[TestClient]:  # noqa: F811
    s = settings.model_copy(update={"youtube_api_key": SecretStr(YT_KEY)})
    with TestClient(create_app(s)) as c:
        yield c


def test_verify_run_updates_db(
    api: TestClient,
    settings: Settings,  # noqa: F811
    admin: httpx.Client,  # noqa: F811
    world: dict,  # noqa: F811
    seeded: dict,
):
    yt_calls: list[httpx.Request] = []

    def youtube(request: httpx.Request) -> httpx.Response:
        yt_calls.append(request)
        return httpx.Response(
            200,
            json={
                "items": [
                    yt_item(VID_CC, 452700, license="creativeCommon"),
                    yt_item(VID_UNKNOWN, 270000, license="youtube"),
                ]
            },
        )

    h = {
        "Authorization": f"Bearer {world['access_token']}",
        "Idempotency-Key": f"it-{uuid.uuid4()}",
    }
    with respx.mock(assert_all_called=False) as router:
        router.get(VIDEOS_URL).mock(side_effect=youtube)
        router.route().pass_through()
        resp = api.post("/v1/verify-runs", headers=h)
        replay = api.post("/v1/verify-runs", headers=h)
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert (body["checked"], body["skipped_recent"], body["failed"]) == (2, 0, 1)
    assert body["job"]["status"] == "done"
    assert replay.json() == body and len(yt_calls) == 1
    assert yt_calls[0].headers["X-Goog-Api-Key"] == YT_KEY

    sh = service_headers(settings)
    cands = seeded["cands"]
    obs = admin.get(
        rest_url(settings, "observations"),
        headers=sh,
        params={"select": "id,candidate_id,view_count", "job_id": f"eq.{body['job']['id']}"},
    ).json()
    assert {o["candidate_id"]: o["view_count"] for o in obs} == {
        cands[VID_CC]: 452700,
        cands[VID_UNKNOWN]: 270000,
    }
    new_obs = {o["candidate_id"]: o["id"] for o in obs}

    verdicts = admin.get(
        rest_url(settings, "candidate_verdicts"),
        headers=sh,
        params={
            "select": (
                "candidate_id,status,reason,growth_pct,prev_observation_id,curr_observation_id"
            ),
            "profile_id": f"eq.{seeded['profile_id']}",
        },
    ).json()
    by_cand = {v["candidate_id"]: v for v in verdicts}
    cc = by_cand[cands[VID_CC]]
    assert cc["status"] == "producible" and float(cc["growth_pct"]) == 0.6
    assert cc["prev_observation_id"] == seeded["prev_id"]
    assert cc["curr_observation_id"] == new_obs[cands[VID_CC]]
    unk = by_cand[cands[VID_UNKNOWN]]
    assert unk["status"] == "excluded" and unk["reason"] == "not_cc"
    assert cands[VID_GONE] not in by_cand

    rows = admin.get(
        rest_url(settings, "candidates"),
        headers=sh,
        params={
            "select": "id,rep_status,license_cc,channel_id,status_changed_at",
            "workspace_id": f"eq.{world['workspace_id']}",
        },
    ).json()
    c = {r["id"]: r for r in rows}
    assert c[cands[VID_CC]]["rep_status"] == "producible"
    assert c[cands[VID_CC]]["license_cc"] is True and c[cands[VID_CC]]["channel_id"] == CHANNEL_X
    assert c[cands[VID_CC]]["status_changed_at"] is not None
    assert c[cands[VID_UNKNOWN]]["rep_status"] == "excluded"
    assert c[cands[VID_UNKNOWN]]["license_cc"] is False
    assert c[cands[VID_GONE]]["rep_status"] == "pending"  # 이전 판정 유지


def test_new_key_within_60s_rate_limited(
    api: TestClient,
    settings: Settings,  # noqa: F811
    admin: httpx.Client,  # noqa: F811
    world: dict,  # noqa: F811
    seeded: dict,
):
    """직전 verify job 생성 후 60초 안에 새 키로 요청하면 429 RATE_LIMITED(job 생성 없음)."""
    r = admin.post(
        rest_url(settings, "jobs"),
        headers=service_headers(settings),
        json={
            "workspace_id": world["workspace_id"],
            "kind": "verify",
            "status": "done",
            "idempotency_key": f"it-recent-{uuid.uuid4()}",
        },
    )
    assert r.status_code == 201, r.status_code
    h = {
        "Authorization": f"Bearer {world['access_token']}",
        "Idempotency-Key": f"it-{uuid.uuid4()}",
    }
    with respx.mock(assert_all_called=False) as router:
        yt = router.get(VIDEOS_URL).mock(return_value=httpx.Response(200, json={"items": []}))
        router.route().pass_through()
        resp = api.post("/v1/verify-runs", headers=h)
    assert resp.status_code == 429 and resp.json()["code"] == "RATE_LIMITED"
    assert not yt.called
