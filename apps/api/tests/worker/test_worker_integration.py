"""워커 API 로컬 Supabase 통합 테스트(-m integration). YouTube만 respx 목, DB는 실제 로컬.

키는 셸 환경변수로만(SUPABASE_URL · SUPABASE_SERVICE_ROLE_KEY · SUPABASE_PUBLISHABLE_KEY).
흐름: issue CLI로 워커 토큰 2개 발급 → 동시 claim(1건만 성공) → heartbeat → candidates → finish.
"""

import asyncio
import uuid

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
from tests.youtube.conftest import CHANNEL_X, YT_KEY, yt_item

pytestmark = pytest.mark.integration

VID_NEW = "itWrkNEW001"
VID_GONE = "itWrkGONE02"


def _issue(capsys, ws: str, name: str, admin: httpx.Client) -> str:  # noqa: F811
    assert worker_tokens(["issue", "--workspace", ws, "--name", name], client=admin) == 0
    return capsys.readouterr().out.strip()


def test_worker_flow(
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
            "name": "통합 KR",
            "market": "KR",
            "max_growth_pct": 5,
        },
    )
    assert r.status_code == 201, r.status_code
    job_id = str(uuid.uuid4())
    r = admin.post(
        rest_url(settings, "jobs"),
        headers=h,
        json={
            "id": job_id,
            "workspace_id": ws,
            "kind": "collect",
            "status": "queued",
            "profile_ids": [profile_id],
            "idempotency_key": f"it-{job_id}",
        },
    )
    assert r.status_code == 201, r.status_code
    token_a = _issue(capsys, ws, "it-worker-a", admin)
    token_b = _issue(capsys, ws, "it-worker-b", admin)
    worker_a = token_a.split(".")[0]

    app = create_app(settings.model_copy(update={"youtube_api_key": SecretStr(YT_KEY)}))

    def yt(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": [yt_item(VID_NEW, 1234)]})

    async def run() -> dict:
        out: dict = {}
        transport = httpx.ASGITransport(app=app)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:

                def auth(t: str) -> dict:
                    return {"Authorization": f"Bearer {t}"}

                claims = await asyncio.gather(
                    c.post("/worker/v1/jobs/claim", headers=auth(token_a)),
                    c.post("/worker/v1/jobs/claim", headers=auth(token_b)),
                )
                out["claims"] = sorted(r.status_code for r in claims)
                winner = token_a if claims[0].status_code == 200 else token_b
                out["winner"] = winner.split(".")[0]
                again = await c.post("/worker/v1/jobs/claim", headers=auth(winner))
                out["again"] = (again.status_code, again.json()["job"]["id"])
                hb = await c.post(
                    "/worker/v1/heartbeat",
                    headers=auth(winner),
                    json={
                        "job_id": job_id,
                        "chrome": [{"profile_id": profile_id, "state": "ready"}],
                    },
                )
                out["hb"] = (hb.status_code, hb.json())
                cand = await c.post(
                    f"/worker/v1/jobs/{job_id}/candidates",
                    headers=auth(winner),
                    json={
                        "profile_id": profile_id,
                        "items": [
                            {
                                "video_id": VID_NEW,
                                "title": "워커 제목",
                                "market": "KR",
                                "format": "long",
                                "genre": "음악",
                            },
                            {"video_id": VID_NEW, "title": "중복", "market": "KR"},
                            {"video_id": VID_GONE, "title": "없음", "market": "KR"},
                        ],
                    },
                )
                out["cand"] = (cand.status_code, cand.json())
                fin = await c.post(
                    f"/worker/v1/jobs/{job_id}/finish",
                    headers=auth(winner),
                    json={"status": "done"},
                )
                out["fin"] = (fin.status_code, fin.json())
                late = await c.post(
                    "/worker/v1/heartbeat", headers=auth(winner), json={"job_id": job_id}
                )
                out["late"] = late.status_code
        return out

    with respx.mock(assert_all_called=False) as router:
        router.get(VIDEOS_URL).mock(side_effect=yt)
        router.route().pass_through()
        out = asyncio.run(run())

    assert out["claims"] == [200, 204]
    assert out["again"] == (200, job_id)
    assert out["hb"] == (200, {"stop_requested": False})
    assert out["cand"] == (200, {"accepted": 1, "duplicates": 1, "unavailable": 1})
    assert out["fin"] == (200, {"job": {"status": "done"}})
    assert out["late"] == 409

    sh = service_headers(settings)

    def get(table: str, **params: str) -> list[dict]:
        resp = admin.get(rest_url(settings, table), headers=sh, params=params)
        assert resp.status_code == 200, resp.status_code
        return resp.json()

    job = get("jobs", select="status,claimed_by,finished_at,lookup_count,error", id=f"eq.{job_id}")[
        0
    ]
    assert job["status"] == "done" and job["claimed_by"] == out["winner"]
    assert job["finished_at"] is not None
    assert job["lookup_count"] == 2 and job["error"] is None  # 새 후보 2건만 조회 예약
    cands = get(
        "candidates",
        select="id,video_id,title,thumbnail_url,channel_id,license_cc,rep_status,first_job_id,genre",
        workspace_id=f"eq.{ws}",
    )
    assert len(cands) == 1
    c = cands[0]
    assert c["video_id"] == VID_NEW and c["title"] == "t" and c["genre"] == "음악"
    assert c["thumbnail_url"] == f"https://i.ytimg.com/vi/{VID_NEW}/hqdefault.jpg"
    assert c["channel_id"] == CHANNEL_X and c["license_cc"] is True
    assert c["rep_status"] == "pending" and c["first_job_id"] == job_id
    obs = get("observations", select="view_count,job_id", candidate_id=f"eq.{c['id']}")
    assert obs == [{"view_count": 1234, "job_id": job_id}]
    ver = get("candidate_verdicts", select="status,reason", candidate_id=f"eq.{c['id']}")
    assert ver == [{"status": "pending", "reason": "no_prev"}]
    runs = get(
        "job_profile_runs", select="collected_count,status,chrome_state", job_id=f"eq.{job_id}"
    )
    assert runs == [{"collected_count": 1, "status": "done", "chrome_state": "ready"}]
    hb = get("worker_heartbeats", select="worker_id,current_job_id", workspace_id=f"eq.{ws}")
    assert {r["worker_id"] for r in hb} >= {out["winner"]}

    # CLI로 폐기한 토큰은 401
    assert worker_tokens(["revoke", "--id", worker_a], client=admin) == 0

    async def revoked() -> int:
        transport = httpx.ASGITransport(app=app)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
                r = await c.post(
                    "/worker/v1/jobs/claim", headers={"Authorization": f"Bearer {token_a}"}
                )
                return r.status_code

    assert asyncio.run(revoked()) == 401
