"""A-05 로컬 Supabase 통합 테스트(-m integration). YouTube만 respx 목, DB는 실제 로컬.

키는 셸 환경변수로만(SUPABASE_URL · SUPABASE_SERVICE_ROLE_KEY · SUPABASE_PUBLISHABLE_KEY).
흐름: A-05 POST → issue CLI 토큰으로 W-01 claim → W-03 → A-05 stop(stop_requested)
→ W-04 stopped → A-05 GET(result·후보 보존) → retry 409(중지됨).
흐름 2: 서로 다른 키 동시 POST → 활성 job 1건.
흐름 3: POST → claim → W-03(두 프로필) → W-04 failed → retry → 재수령(resume_from_profile_id).
60초 제한을 넘기려고 테스트 사이에 기존 job의 created_at을 service_role로 과거로 옮긴다.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from pydantic import SecretStr

from app.cli.worker_tokens import main as worker_tokens
from app.config import Settings
from app.main import create_app
from app.supabase import rest_url, service_headers
from app.youtube.client import VIDEOS_URL
from tests.test_integration import admin, settings, world  # noqa: F401  (fixture 재사용)
from tests.youtube.conftest import YT_KEY, yt_item

pytestmark = pytest.mark.integration

VID_A = "itColSTOP01"
VID_B = "itColRTRY01"
VID_C = "itColRTRY02"


def _age_jobs(settings: Settings, admin: httpx.Client, ws: str) -> None:  # noqa: F811
    old = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    r = admin.patch(
        rest_url(settings, "jobs"),
        headers=service_headers(settings),
        params={"workspace_id": f"eq.{ws}"},
        json={"created_at": old},
    )
    assert r.status_code in (200, 204), r.status_code


def _profile(settings: Settings, admin: httpx.Client, ws: str, name: str) -> str:  # noqa: F811
    pid = str(uuid.uuid4())
    r = admin.post(
        rest_url(settings, "profiles"),
        headers={**service_headers(settings), "Prefer": "return=minimal"},
        json={"id": pid, "workspace_id": ws, "name": name, "market": "KR", "max_growth_pct": 5},
    )
    assert r.status_code == 201, r.status_code
    return pid


def test_collect_job_stop_flow(
    capsys,
    settings: Settings,  # noqa: F811
    admin: httpx.Client,  # noqa: F811
    world: dict,  # noqa: F811
):
    ws = world["workspace_id"]
    h = {**service_headers(settings), "Prefer": "return=representation"}
    profile_id = str(uuid.uuid4())
    r = admin.post(
        rest_url(settings, "profiles"),
        headers=h,
        json={
            "id": profile_id,
            "workspace_id": ws,
            "name": "수집 통합 KR",
            "market": "KR",
            "max_growth_pct": 5,
            "selected": True,
        },
    )
    assert r.status_code == 201, r.status_code
    assert worker_tokens(["issue", "--workspace", ws, "--name", "it-collect"], client=admin) == 0
    worker_token = capsys.readouterr().out.strip()

    app = create_app(settings.model_copy(update={"youtube_api_key": SecretStr(YT_KEY)}))
    user = {"Authorization": f"Bearer {world['access_token']}"}
    worker = {"Authorization": f"Bearer {worker_token}"}

    def yt(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": [yt_item(VID_A, 1000)]})

    async def run() -> dict:
        out: dict = {}
        transport = httpx.ASGITransport(app=app)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
                key = {**user, "Idempotency-Key": f"it-{uuid.uuid4()}"}
                post = await c.post("/v1/collect-jobs", headers=key)
                out["post"] = (post.status_code, post.json())
                job_id = post.json()["job"]["id"]
                out["job_id"] = job_id
                replay = await c.post("/v1/collect-jobs", headers=key)
                out["replay"] = (replay.status_code, replay.json()["job"]["id"])
                claim = await c.post("/worker/v1/jobs/claim", headers=worker)
                out["claim"] = (claim.status_code, claim.json())
                cand = await c.post(
                    f"/worker/v1/jobs/{job_id}/candidates",
                    headers=worker,
                    json={
                        "profile_id": profile_id,
                        "items": [{"video_id": VID_A, "title": "w", "market": "KR"}],
                    },
                )
                out["cand"] = (cand.status_code, cand.json())
                stop = await c.post(f"/v1/collect-jobs/{job_id}/stop", headers=user)
                out["stop"] = (stop.status_code, stop.json()["job"])
                hb = await c.post("/worker/v1/heartbeat", headers=worker, json={"job_id": job_id})
                out["hb"] = hb.json()
                fin = await c.post(
                    f"/worker/v1/jobs/{job_id}/finish", headers=worker, json={"status": "stopped"}
                )
                out["fin"] = (fin.status_code, fin.json())
                get = await c.get(f"/v1/collect-jobs/{job_id}", headers=user)
                out["get"] = (get.status_code, get.json()["job"])
                retry = await c.post(f"/v1/collect-jobs/{job_id}/retry", headers=user)
                out["retry"] = retry.status_code
                again = await c.post(f"/v1/collect-jobs/{job_id}/stop", headers=user)
                out["again"] = again.status_code
        return out

    with respx.mock(assert_all_called=False) as router:
        router.get(VIDEOS_URL).mock(side_effect=yt)
        router.route().pass_through()
        out = asyncio.run(run())

    job_id = out["job_id"]
    status, body = out["post"]
    assert status == 202, body
    assert body["job"]["status"] == "queued"
    assert [p["profile_id"] for p in body["job"]["profiles"]] == [profile_id]
    assert out["replay"] == (200, job_id)
    assert out["claim"][0] == 200 and out["claim"][1]["job"]["id"] == job_id
    assert out["claim"][1]["job"]["limit"] == 200
    assert out["cand"] == (200, {"accepted": 1, "duplicates": 0, "unavailable": 0})
    assert out["stop"][0] == 200
    assert out["stop"][1]["status"] == "running" and out["stop"][1]["stop_requested"] is True
    assert out["hb"] == {"stop_requested": True}
    assert out["fin"] == (200, {"job": {"status": "stopped"}})
    status, got = out["get"]
    assert status == 200
    assert got["status"] == "stopped" and got["error"] == "stopped_by_user"
    assert got["result"] == {"candidates": 1, "producible": 0, "pending": 1}
    assert got["profiles"][0]["collected_count"] == 1
    assert got["worker_online"] is True and got["worker_last_seen_at"] is not None
    assert out["retry"] == 409 and out["again"] == 409

    sh = service_headers(settings)
    rows = admin.get(
        rest_url(settings, "candidates"),
        headers=sh,
        params={"select": "video_id,first_job_id", "workspace_id": f"eq.{ws}"},
    ).json()
    assert rows == [{"video_id": VID_A, "first_job_id": job_id}]  # 중지 후 후보 보존


def test_concurrent_posts_different_keys(
    settings: Settings,  # noqa: F811
    admin: httpx.Client,  # noqa: F811
    world: dict,  # noqa: F811
):
    ws = world["workspace_id"]
    _age_jobs(settings, admin, ws)
    app = create_app(settings)
    user = {"Authorization": f"Bearer {world['access_token']}"}
    tag = uuid.uuid4().hex[:8]

    async def run() -> list[httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
                rs = await asyncio.gather(
                    *(
                        c.post(
                            "/v1/collect-jobs",
                            headers={**user, "Idempotency-Key": f"it-race-{tag}-{i}"},
                        )
                        for i in range(2)
                    )
                )
                for r in rs:  # 다음 테스트를 위해 만든 job을 멈춘다(queued → stopped)
                    if r.status_code == 202:
                        jid = r.json()["job"]["id"]
                        stop = await c.post(f"/v1/collect-jobs/{jid}/stop", headers=user)
                        assert stop.status_code == 200
                return list(rs)

    rs = asyncio.run(run())
    codes = sorted(r.status_code for r in rs)
    assert codes[0] == 202 and codes[1] in (409, 429), codes
    sh = service_headers(settings)
    made = admin.get(
        rest_url(settings, "jobs"),
        headers=sh,
        params={"select": "status", "idempotency_key": f"like.it-race-{tag}-*"},
    ).json()
    assert made == [{"status": "stopped"}]  # 두 번째 요청은 job을 만들지 못함


def test_collect_job_retry_flow(
    capsys,
    settings: Settings,  # noqa: F811
    admin: httpx.Client,  # noqa: F811
    world: dict,  # noqa: F811
):
    ws = world["workspace_id"]
    _age_jobs(settings, admin, ws)
    pa = _profile(settings, admin, ws, "재시도 A")
    pb = _profile(settings, admin, ws, "재시도 B")
    assert worker_tokens(["issue", "--workspace", ws, "--name", "it-retry"], client=admin) == 0
    worker = {"Authorization": f"Bearer {capsys.readouterr().out.strip()}"}
    user = {"Authorization": f"Bearer {world['access_token']}"}
    app = create_app(settings.model_copy(update={"youtube_api_key": SecretStr(YT_KEY)}))

    def yt(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": [yt_item(VID_B, 10), yt_item(VID_C, 20)]})

    async def run() -> dict:
        out: dict = {}
        transport = httpx.ASGITransport(app=app)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
                post = await c.post(
                    "/v1/collect-jobs",
                    headers={**user, "Idempotency-Key": f"it-{uuid.uuid4()}"},
                    json={"profile_ids": [pa, pb]},
                )
                assert post.status_code == 202, post.json()
                jid = post.json()["job"]["id"]
                out["jid"] = jid
                claim = await c.post("/worker/v1/jobs/claim", headers=worker)
                out["claim1"] = claim.json()["job"]
                for pid, vid in ((pa, VID_B), (pb, VID_C)):
                    items = [{"video_id": vid, "title": "w", "market": "KR"}]
                    r = await c.post(
                        f"/worker/v1/jobs/{jid}/candidates",
                        headers=worker,
                        json={"profile_id": pid, "items": items},
                    )
                    assert r.status_code == 200, r.json()
                fin = await c.post(
                    f"/worker/v1/jobs/{jid}/finish",
                    headers=worker,
                    json={"status": "failed", "error": "chrome_failed"},
                )
                out["fin"] = fin.status_code
                retry = await c.post(f"/v1/collect-jobs/{jid}/retry", headers=user)
                out["retry"] = (retry.status_code, retry.json()["job"])
                claim = await c.post("/worker/v1/jobs/claim", headers=worker)
                out["claim2"] = (claim.status_code, claim.json()["job"])
                get = await c.get(f"/v1/collect-jobs/{jid}", headers=user)
                out["get"] = get.json()["job"]
                done = await c.post(
                    f"/worker/v1/jobs/{jid}/finish", headers=worker, json={"status": "done"}
                )
                out["done"] = done.status_code
        return out

    with respx.mock(assert_all_called=False) as router:
        router.get(VIDEOS_URL).mock(side_effect=yt)
        router.route().pass_through()
        out = asyncio.run(run())

    jid = out["jid"]
    assert out["claim1"]["id"] == jid and out["claim1"]["resume_from_profile_id"] is None
    assert out["fin"] == 200
    status, retried = out["retry"]
    assert status == 200 and retried["status"] == "retrying" and retried["retry_count"] == 1
    assert [p["status"] for p in retried["profiles"]] == ["done", "pending"]
    status, claimed = out["claim2"]
    assert status == 200 and claimed["id"] == jid
    assert claimed["resume_from_profile_id"] == pb and claimed["limit"] == 200
    assert out["get"]["status"] == "running" and out["get"]["error"] is None
    assert out["get"]["result"]["candidates"] == 2  # 재시도 전 수집 후보 유지
    assert out["done"] == 200
    job = admin.get(
        rest_url(settings, "jobs"),
        headers=service_headers(settings),
        params={"select": "lookup_count,retry_count,status", "id": f"eq.{jid}"},
    ).json()[0]
    assert job == {"lookup_count": 2, "retry_count": 1, "status": "done"}  # lookup 초기화 안 함
