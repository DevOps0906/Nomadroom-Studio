"""A-07 단위 테스트용 가짜 PostgREST(메모리)와 YouTube videos.list 목(respx)."""

import json
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.main import create_app
from app.youtube.client import VIDEOS_URL
from tests.conftest import JWKS_URL, SUPABASE_URL, WORKSPACE_ID, make_settings

REST = f"{SUPABASE_URL}/rest/v1"
# Google API 키 형식(AIza + 35자) 가짜 값
YT_KEY = "AIza" + "Sy" + "T" * 31 + "x9"
PROFILE_KR = "00000000-0000-4000-8000-0000000000a1"
PROFILE_JP = "00000000-0000-4000-8000-0000000000a2"
# YouTube 채널 id 형식(UC + 22자)
CHANNEL_X = "UC" + "x" * 22
BROADCASTER = "UCbroadcaster" + "0" * 11


def video_id(n: int) -> str:
    return f"vid{n:08d}"  # 11자


def cand_id(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012d}"


def target(n: int, latest: datetime | None = None, **over: Any) -> dict:
    row = {
        "id": cand_id(n),
        "video_id": video_id(n),
        "title": f"후보 {n}",
        "category": None,
        "format": "long",
        "market": "KR",
        "license_cc": None,
        "is_broadcaster": False,
        "latest_observed_at": latest.isoformat() if latest else None,
    }
    row.update(over)
    return row


def yt_item(
    vid: str, views: int, license: str = "creativeCommon", channel: str = CHANNEL_X
) -> dict:
    return {
        "kind": "youtube#video",
        "id": vid,
        "snippet": {"channelId": channel, "channelTitle": f"채널 {channel}", "title": "t"},
        "statistics": {"viewCount": str(views), "likeCount": "1"},
        "status": {"license": license, "privacyStatus": "public"},
    }


@dataclass
class FakeDB:
    profiles: list[dict] = field(default_factory=list)
    targets: list[dict] = field(default_factory=list)
    skipped: int = 0
    counts: dict[str, int] = field(
        default_factory=lambda: {"producible": 1, "pending": 2, "excluded": 3, "used": 4}
    )
    jobs: list[dict] = field(default_factory=list)
    observations: list[dict] = field(default_factory=list)
    verdicts: list[dict] = field(default_factory=list)
    broadcasters: list[str] = field(default_factory=lambda: [BROADCASTER])
    quota_units: int = 0
    applied: list[dict] = field(default_factory=list)
    fail_apply_calls: set[int] = field(default_factory=set)
    apply_calls: int = 0
    job_insert_conflict: str | None = None  # 강제 23505 제약 이름
    youtube: dict[str, dict] = field(default_factory=dict)  # video_id → item
    youtube_calls: list[httpx.Request] = field(default_factory=list)
    youtube_error: httpx.Response | Exception | None = None
    finish_failures: int = 0  # 종료 PATCH(id 지정)를 이 횟수만큼 500으로 실패
    observation_params: list[dict[str, str]] = field(default_factory=list)
    fail_observation_calls: set[int] = field(default_factory=set)  # n번째 관측 조회를 500으로
    on_youtube: Callable[[], None] | None = None  # videos.list 응답 직전 훅


def _params(request: httpx.Request) -> dict[str, str]:
    return {k: v[-1] for k, v in parse_qs(request.url.query.decode()).items()}


def _conflict(name: str) -> httpx.Response:
    return httpx.Response(
        409,
        json={
            "code": "23505",
            "details": "Key already exists.",
            "hint": None,
            "message": f'duplicate key value violates unique constraint "{name}"',
        },
    )


def install(router: respx.MockRouter, db: FakeDB) -> None:
    def jobs(request: httpx.Request) -> httpx.Response:
        p = _params(request)
        if request.method == "GET":
            if "idempotency_key" in p:
                key = p["idempotency_key"].removeprefix("eq.")
                return httpx.Response(200, json=[j for j in db.jobs if j["idempotency_key"] == key])
            # 60초 제한 조회
            assert p["kind"] == "eq.verify" and p["created_at"].startswith("gt.")
            cut = datetime.fromisoformat(p["created_at"].removeprefix("gt."))
            recent = [
                j
                for j in db.jobs
                if j["kind"] == "verify"
                and j.get("created_at")
                and datetime.fromisoformat(j["created_at"]) > cut
            ]
            return httpx.Response(200, json=recent)
        body = json.loads(request.content)
        if request.method == "POST":
            if db.job_insert_conflict:
                return _conflict(db.job_insert_conflict)
            if any(j["idempotency_key"] == body["idempotency_key"] for j in db.jobs):
                return _conflict("jobs_workspace_id_idempotency_key_key")
            if any(j["kind"] == "verify" and j["status"] in ("queued", "running") for j in db.jobs):
                return _conflict("jobs_one_active_per_kind_idx")
            job = {
                "id": str(uuid.uuid4()),
                "result": None,
                "error": None,
                "created_at": datetime.now(UTC).isoformat(),
                **body,
            }
            db.jobs.append(job)
            return httpx.Response(201, json=[job])
        # PATCH
        if "id" in p:
            if db.finish_failures > 0:
                db.finish_failures -= 1
                return httpx.Response(500, json={"message": "boom"})
            for j in db.jobs:
                if j["id"] == p["id"].removeprefix("eq."):
                    j.update(body)
            return httpx.Response(204)
        assert p["status"] == "in.(queued,running)" and p["kind"] == "eq.verify"
        cut = datetime.now(UTC) - timedelta(minutes=10)
        for j in db.jobs:
            started = datetime.fromisoformat(j.get("started_at") or j["created_at"])
            if j["kind"] == "verify" and j["status"] in ("queued", "running") and started < cut:
                j.update(body)
        return httpx.Response(204)

    def view(request: httpx.Request) -> httpx.Response:
        p = _params(request)
        if request.method == "HEAD":
            if "display_status" in p:
                n = db.counts[p["display_status"].removeprefix("eq.")]
            else:
                assert p["latest_observed_at"].startswith("gt.") and p["used"] == "is.false"
                n = db.skipped
            return httpx.Response(200, headers={"content-range": f"*/{n}"})
        assert p["used"] == "is.false" and p["limit"] == "200"
        assert p["order"] == "latest_observed_at.asc.nullsfirst,id.asc"
        return httpx.Response(200, json=db.targets)

    def observations(request: httpx.Request) -> httpx.Response:
        p = _params(request)
        db.observation_params.append(p)
        if len(db.observation_params) in db.fail_observation_calls:
            return httpx.Response(500, json={"message": "boom"})
        assert p["order"] == "candidate_id.asc,observed_at.desc"
        ids = p["candidate_id"].removeprefix("in.(").removesuffix(")").split(",")
        cut = datetime.fromisoformat(p["observed_at"].removeprefix("gte."))
        rows = [
            o
            for o in db.observations
            if o["candidate_id"] in ids and datetime.fromisoformat(o["observed_at"]) >= cut
        ]
        rows.sort(key=lambda o: o["observed_at"], reverse=True)
        rows.sort(key=lambda o: o["candidate_id"])
        return httpx.Response(200, json=rows)

    def verdicts(request: httpx.Request) -> httpx.Response:
        ids = _params(request)["candidate_id"].removeprefix("in.(").removesuffix(")").split(",")
        return httpx.Response(200, json=[v for v in db.verdicts if v["candidate_id"] in ids])

    def reserve(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if db.quota_units + body["p_units"] <= body["p_limit"]:
            db.quota_units += body["p_units"]
            return httpx.Response(200, json=True)
        return httpx.Response(200, json=False)

    def apply(request: httpx.Request) -> httpx.Response:
        db.apply_calls += 1
        if db.apply_calls in db.fail_apply_calls:
            return httpx.Response(500, json={"message": "boom"})
        body = json.loads(request.content)
        job = next((j for j in db.jobs if j["id"] == body["p_job"]), None)
        if job is None or job["status"] != "running":  # 실제 RPC는 NR004
            return httpx.Response(400, json={"code": "NR004", "message": "진행 중인 작업 아님"})
        db.applied.append(body)
        return httpx.Response(200, json=len(body["p_payload"]["items"]))

    def youtube(request: httpx.Request) -> httpx.Response:
        db.youtube_calls.append(request)
        if db.on_youtube is not None:
            db.on_youtube()
        if isinstance(db.youtube_error, Exception):
            raise db.youtube_error
        if db.youtube_error is not None:
            return db.youtube_error
        ids = _params(request)["id"].split(",")
        items = [db.youtube[i] for i in ids if i in db.youtube]
        return httpx.Response(200, json={"kind": "youtube#videoListResponse", "items": items})

    router.route(url=f"{REST}/jobs").mock(side_effect=jobs)
    router.route(url=f"{REST}/candidate_list_v").mock(side_effect=view)
    router.get(f"{REST}/profiles").mock(side_effect=lambda r: httpx.Response(200, json=db.profiles))
    router.get(f"{REST}/broadcaster_channels").mock(
        side_effect=lambda r: httpx.Response(200, json=[{"channel_id": c} for c in db.broadcasters])
    )
    router.get(f"{REST}/observations").mock(side_effect=observations)
    router.get(f"{REST}/candidate_verdicts").mock(side_effect=verdicts)
    router.post(f"{REST}/rpc/reserve_quota").mock(side_effect=reserve)
    router.post(f"{REST}/rpc/apply_verify_batch").mock(side_effect=apply)
    router.get(VIDEOS_URL).mock(side_effect=youtube)


def profile(pid: str, name: str, market: str, **over: Any) -> dict:
    row = {
        "id": pid,
        "name": name,
        "market": market,
        "format": "all",
        "category": None,
        "min_views": 0,
        "max_growth_pct": 5,
        "keywords": [],
        "cc_only": False,
        "include_broadcast": True,
        "selected": True,
        "updated_at": "2026-11-01T00:00:00+00:00",
    }
    row.update(over)
    return row


@pytest.fixture
def db() -> FakeDB:
    return FakeDB(
        profiles=[profile(PROFILE_KR, "가 한국", "KR"), profile(PROFILE_JP, "나 일본", "JP")]
    )


@pytest.fixture
def api(mock_supabase: respx.MockRouter, jwks_payload: dict, db: FakeDB) -> Iterator[TestClient]:
    mock_supabase.get(JWKS_URL).mock(return_value=httpx.Response(200, json=jwks_payload))
    mock_supabase.get(f"{REST}/workspace_members").mock(
        return_value=httpx.Response(200, json=[{"workspace_id": str(WORKSPACE_ID)}])
    )
    install(mock_supabase, db)
    app = create_app(make_settings(youtube_api_key=YT_KEY))
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def headers(make_token) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token()}", "Idempotency-Key": "run-1"}
