"""A-05 로컬 Supabase 통합 테스트(-m integration). YouTube만 respx 목, DB는 실제 로컬.

키는 셸 환경변수로만(SUPABASE_URL · SUPABASE_SERVICE_ROLE_KEY · SUPABASE_PUBLISHABLE_KEY).
task-019 이후 A-05 POST는 검색 job만 만든다.
vidIQ(워커) 흐름은 queued job을 service_role로 직접 넣어 확인한다.
흐름: vidIQ queued job → issue CLI 토큰으로 W-01 claim → W-03 → A-05 stop(stop_requested)
→ W-04 stopped → A-05 GET(result·후보 보존) → retry 409(중지됨).
흐름 2: 서로 다른 키 동시 POST(검색) → job 1건.
흐름 3: vidIQ queued job → claim → W-03(두 프로필) → W-04 failed → retry
→ 재수령(resume_from_profile_id).
60초 제한을 넘기려고 테스트 사이에 기존 job의 created_at을 service_role로 과거로 옮긴다.
검색 할당량 카운터는 서버 공용이라 검색 테스트 전에 오늘 사용량을 0으로 되돌린다.
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
from app.youtube.client import SEARCH_URL, VIDEOS_URL
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


def _reset_quota(settings: Settings, admin: httpx.Client) -> None:  # noqa: F811
    r = admin.patch(
        rest_url(settings, "api_quota_daily"),
        headers=service_headers(settings),
        params={"day": "gte.2000-01-01"},
        json={"units": 0, "search_units": 0},
    )
    assert r.status_code in (200, 204), r.status_code


def _vidiq_job(settings: Settings, admin: httpx.Client, ws: str, pids: list[str]) -> str:  # noqa: F811
    """워커 흐름용 queued vidIQ job과 실행 행(task-019 이전 POST가 만들던 것과 같은 모양)."""
    jid = str(uuid.uuid4())
    h = {**service_headers(settings), "Prefer": "return=minimal"}
    r = admin.post(
        rest_url(settings, "jobs"),
        headers=h,
        json={
            "id": jid,
            "workspace_id": ws,
            "kind": "collect",
            "status": "queued",
            "profile_ids": pids,
            "params": {"limit": 200},
            "idempotency_key": f"it-vidiq-{jid}",
        },
    )
    assert r.status_code == 201, r.status_code
    runs = [
        {"workspace_id": ws, "job_id": jid, "profile_id": pid, "position": i, "status": "pending"}
        for i, pid in enumerate(pids)
    ]
    r = admin.post(rest_url(settings, "job_profile_runs"), headers=h, json=runs)
    assert r.status_code == 201, r.status_code
    return jid


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
                job_id = _vidiq_job(settings, admin, ws, [profile_id])
                out["job_id"] = job_id
                pre = await c.get(f"/v1/collect-jobs/{job_id}", headers=user)
                out["pre"] = (pre.status_code, pre.json()["job"])
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
    status, body = out["pre"]
    assert status == 200, body
    assert body["status"] == "queued" and body["source"] == "vidiq"
    assert [p["profile_id"] for p in body["profiles"]] == [profile_id]
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
    _reset_quota(settings, admin)
    app = create_app(settings.model_copy(update={"youtube_api_key": SecretStr(YT_KEY)}))
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
                return list(rs)

    with respx.mock(assert_all_called=False) as router:
        router.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={"items": []}))
        router.route().pass_through()
        rs = asyncio.run(run())
    codes = sorted(r.status_code for r in rs)
    assert codes[0] == 202 and codes[1] in (409, 429), codes
    sh = service_headers(settings)
    made = admin.get(
        rest_url(settings, "jobs"),
        headers=sh,
        params={"select": "status", "idempotency_key": f"like.it-race-{tag}-*"},
    ).json()
    assert made == [{"status": "done"}]  # 두 번째 요청은 job을 만들지 못함


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
                jid = _vidiq_job(settings, admin, ws, [pa, pb])
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
    assert out["get"]["result"] is None  # 진행 중에는 집계 생략(task-013)
    kept = admin.get(
        rest_url(settings, "candidates"),
        headers=service_headers(settings),
        params={"select": "id", "first_job_id": f"eq.{jid}"},
    ).json()
    assert len(kept) == 2  # 재시도 전 수집 후보 유지
    assert out["done"] == 200
    job = admin.get(
        rest_url(settings, "jobs"),
        headers=service_headers(settings),
        params={"select": "lookup_count,retry_count,status", "id": f"eq.{jid}"},
    ).json()[0]
    assert job == {"lookup_count": 2, "retry_count": 1, "status": "done"}  # lookup 초기화 안 함


VID_S1 = "itSrchVID01"
VID_S2 = "itSrchVID02"
VID_S3 = "itSrchVID03"


def _yt_video(vid: str, views: int, duration: str) -> dict:
    item = yt_item(vid, views)
    item["contentDetails"] = {"duration": duration}
    return item


def test_search_collect_flow(
    capsys,
    settings: Settings,  # noqa: F811
    admin: httpx.Client,  # noqa: F811
    world: dict,  # noqa: F811
):
    """검색 POST(동기) → done·후보·다프로필 판정 → claim 204 · stop 409 · 같은 키 200
    → 둘째 검색 실패(upstream_error) → retry(남은 프로필만) → done."""
    ws = world["workspace_id"]
    _age_jobs(settings, admin, ws)
    _reset_quota(settings, admin)
    pa = _profile(settings, admin, ws, "검색 A")
    pb = _profile(settings, admin, ws, "검색 B")
    assert worker_tokens(["issue", "--workspace", ws, "--name", "it-search"], client=admin) == 0
    worker = {"Authorization": f"Bearer {capsys.readouterr().out.strip()}"}
    user = {"Authorization": f"Bearer {world['access_token']}"}
    app = create_app(settings.model_copy(update={"youtube_api_key": SecretStr(YT_KEY)}))
    videos = {
        VID_S1: _yt_video(VID_S1, 100, "PT59S"),
        VID_S2: _yt_video(VID_S2, 100, "PT20M"),
        VID_S3: _yt_video(VID_S3, 100, "PT1M"),
    }
    plan: list[httpx.Response] = [
        httpx.Response(
            200, json={"items": [{"id": {"videoId": VID_S1}}, {"id": {"videoId": VID_S2}}]}
        ),
        httpx.Response(200, json={"items": [{"id": {"videoId": VID_S1}}]}),
        # 두 번째 POST: 첫 프로필 성공, 둘째 실패 → 재시도
        httpx.Response(200, json={"items": []}),
        httpx.Response(500, json={"error": {"message": "boom"}}),
        httpx.Response(200, json={"items": [{"id": {"videoId": VID_S3}}]}),
    ]

    def search(request: httpx.Request) -> httpx.Response:
        return plan.pop(0)

    def yt(request: httpx.Request) -> httpx.Response:
        ids = request.url.params["id"].split(",")
        return httpx.Response(200, json={"items": [videos[i] for i in ids if i in videos]})

    async def run() -> dict:
        out: dict = {}
        transport = httpx.ASGITransport(app=app)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
                key = {**user, "Idempotency-Key": f"it-s-{uuid.uuid4()}"}
                post = await c.post("/v1/collect-jobs", headers=key, json={"profile_ids": [pa, pb]})
                out["post"] = (post.status_code, post.json())
                jid = post.json()["job"]["id"]
                out["jid"] = jid
                replay = await c.post("/v1/collect-jobs", headers=key)
                out["replay"] = (replay.status_code, replay.json()["job"]["id"])
                claim = await c.post("/worker/v1/jobs/claim", headers=worker)
                out["claim"] = claim.status_code
                stop = await c.post(f"/v1/collect-jobs/{jid}/stop", headers=user)
                out["stop"] = stop.status_code
                get = await c.get(f"/v1/collect-jobs/{jid}", headers=user)
                out["get"] = get.json()["job"]

                _age_jobs(settings, admin, ws)
                post2 = await c.post(
                    "/v1/collect-jobs",
                    headers={**user, "Idempotency-Key": f"it-s-{uuid.uuid4()}"},
                    json={"profile_ids": [pa, pb]},
                )
                out["post2"] = (post2.status_code, post2.json()["job"])
                jid2 = post2.json()["job"]["id"]
                out["jid2"] = jid2
                early = await c.post(f"/v1/collect-jobs/{jid2}/retry", headers=user)
                out["early"] = (early.status_code, early.json()["code"])
                # 재시도 60초 제한을 넘기려고 직전 실행 시작 시각을 과거로 옮긴다
                r = admin.patch(
                    rest_url(settings, "jobs"),
                    headers=service_headers(settings),
                    params={"id": f"eq.{jid2}"},
                    json={"started_at": (datetime.now(UTC) - timedelta(minutes=2)).isoformat()},
                )
                assert r.status_code in (200, 204), r.status_code
                retry = await c.post(f"/v1/collect-jobs/{jid2}/retry", headers=user)
                out["retry"] = (retry.status_code, retry.json()["job"])
        return out

    with respx.mock(assert_all_called=False) as router:
        router.get(SEARCH_URL).mock(side_effect=search)
        router.get(VIDEOS_URL).mock(side_effect=yt)
        router.route().pass_through()
        out = asyncio.run(run())

    jid = out["jid"]
    status, body = out["post"]
    assert status == 202, body
    job = body["job"]
    assert job["source"] == "youtube_search" and job["status"] == "done"
    assert [(p["status"], p["collected_count"]) for p in job["profiles"]] == [
        ("done", 2),
        ("done", 0),
    ]
    assert out["replay"] == (200, jid)
    assert out["claim"] == 204  # 검색 job은 워커가 수령하지 않는다
    assert out["stop"] == 409
    assert out["get"]["result"]["candidates"] == 2

    sh = service_headers(settings)
    cands = admin.get(
        rest_url(settings, "candidates"),
        headers=sh,
        params={
            "select": "id,video_id,format,market,thumbnail_url",
            "first_job_id": f"eq.{jid}",
            "order": "video_id.asc",
        },
    ).json()
    assert [(c["video_id"], c["format"], c["market"]) for c in cands] == [
        (VID_S1, "short", "KR"),
        (VID_S2, "long", "KR"),
    ]
    verdicts = admin.get(
        rest_url(settings, "candidate_verdicts"),
        headers=sh,
        params={"select": "profile_id", "candidate_id": f"eq.{cands[0]['id']}"},
    ).json()
    assert sorted(v["profile_id"] for v in verdicts) == sorted([pa, pb])

    status, failed = out["post2"]
    assert status == 202 and failed["status"] == "failed" and failed["error"] == "upstream_error"
    assert [p["status"] for p in failed["profiles"]] == ["done", "failed"]
    assert out["early"] == (429, "RATE_LIMITED")
    status, retried = out["retry"]
    assert status == 200, retried
    assert retried["status"] == "done" and retried["retry_count"] == 1
    assert [(p["status"], p["collected_count"]) for p in retried["profiles"]] == [
        ("done", 0),
        ("done", 1),
    ]
    quota = admin.get(
        rest_url(settings, "api_quota_daily"), headers=sh, params={"select": "search_units"}
    ).json()
    assert sum(q["search_units"] for q in quota) == 500  # 200 + 200 + 재시도 100
