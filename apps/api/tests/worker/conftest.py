"""워커 API 단위 테스트용 가짜 PostgREST(메모리)와 YouTube videos.list 목(respx).

필터는 eq·in·is만 해석한다. PATCH는 조건에 맞는 행만 바꾸므로(동기 처리) 실제 DB의
조건부 UPDATE처럼 원자적으로 동작한다.
"""

import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.auth.worker import format_token, hash_secret
from app.main import create_app
from app.youtube.client import VIDEOS_URL
from tests.conftest import OTHER_WORKSPACE_ID, SUPABASE_URL, WORKSPACE_ID, make_settings
from tests.youtube.conftest import YT_KEY, yt_item  # noqa: F401  (테스트에서 재사용)

REST = f"{SUPABASE_URL}/rest/v1"
WS = str(WORKSPACE_ID)
OTHER_WS = str(OTHER_WORKSPACE_ID)
WORKER_A = "00000000-0000-4000-8000-0000000000c1"
WORKER_B = "00000000-0000-4000-8000-0000000000c2"
WORKER_OTHER = "00000000-0000-4000-8000-0000000000c3"
WORKER_REVOKED = "00000000-0000-4000-8000-0000000000c4"
SECRET = "s3cret-worker-token-value-for-tests-0001"
PROFILE_KR = "00000000-0000-4000-8000-0000000000a1"
PROFILE_JP = "00000000-0000-4000-8000-0000000000a2"
PROFILE_OUT = "00000000-0000-4000-8000-0000000000a3"  # 작업에 속하지 않음
JOB = "00000000-0000-4000-8000-0000000000f1"
OTHER_JOB = "00000000-0000-4000-8000-0000000000f2"


def token(worker_id: str) -> str:
    return format_token(uuid.UUID(worker_id), SECRET + worker_id[-2:])


def auth(worker_id: str = WORKER_A) -> dict[str, str]:
    return {"Authorization": f"Bearer {token(worker_id)}"}


def vid(n: int) -> str:
    return f"wvid{n:07d}"  # 11자


def item(n: int, **over: Any) -> dict:
    row = {
        "video_id": vid(n),
        "title": f"워커 제목 {n}",
        "thumbnail_url": f"https://evil.example/{n}.jpg",
        "genre": "음악",
        "category": None,
        "format": "long",
        "market": "KR",
        "channel_id": "UCworker",
        "channel_title": "워커 채널",
    }
    row.update(over)
    return row


def profile(pid: str, market: str, **over: Any) -> dict:
    row = {
        "id": pid,
        "workspace_id": WS,
        "name": f"p-{market}",
        "market": market,
        "format": "all",
        "category": None,
        "min_views": 0,
        "max_growth_pct": 5,
        "keywords": [],
        "cc_only": False,
        "include_broadcast": True,
        "selected": True,
    }
    row.update(over)
    return row


def job(jid: str = JOB, ws: str = WS, status: str = "queued", **over: Any) -> dict:
    row = {
        "id": jid,
        "workspace_id": ws,
        "kind": "collect",
        "status": status,
        "profile_ids": [PROFILE_KR, PROFILE_JP],
        "params": {},
        "stop_requested": False,
        "claimed_by": None,
        "error": None,
        "started_at": None,
        "lookup_count": 0,
        "finished_at": None,
    }
    row.update(over)
    return row


def _params(request: httpx.Request) -> dict[str, str]:
    return {k: v[-1] for k, v in parse_qs(request.url.query.decode()).items()}


_META = {"select", "limit", "order", "on_conflict"}


def _match(row: dict, params: dict[str, str]) -> bool:
    for key, raw in params.items():
        if key in _META:
            continue
        op, _, value = raw.partition(".")
        cur = row.get(key)
        if op == "eq":
            if str(cur) != value:
                return False
        elif op == "in":
            if str(cur) not in value.strip("()").split(","):
                return False
        elif op == "is":
            want = {"true": True, "false": False, "null": None}[value]
            if cur is not want:
                return False
        else:
            raise AssertionError(f"지원하지 않는 필터 {key}={raw}")
    return True


def _select(rows: list[dict], params: dict[str, str]) -> list[dict]:
    out = [r for r in rows if _match(r, params)]
    if "limit" in params:
        out = out[: int(params["limit"])]
    cols = params.get("select")
    if cols and cols != "*":
        out = [{c: r.get(c) for c in cols.split(",")} for r in out]
    return out


@dataclass
class FakeDB:
    workers: list[dict] = field(default_factory=list)
    jobs: list[dict] = field(default_factory=list)
    profiles: list[dict] = field(default_factory=list)
    heartbeats: list[dict] = field(default_factory=list)
    runs: list[dict] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)
    observations: list[dict] = field(default_factory=list)
    verdicts: list[dict] = field(default_factory=list)
    broadcasters: list[dict] = field(default_factory=list)
    quota_ok: bool = True
    quota_calls: int = 0
    lookup_calls: list[dict] = field(default_factory=list)
    apply_calls: list[dict] = field(default_factory=list)
    youtube: dict[str, dict] = field(default_factory=dict)
    youtube_calls: list[httpx.Request] = field(default_factory=list)
    youtube_error: httpx.Response | Exception | None = None
    race_insert: list[str] = field(default_factory=list)  # RPC 직전에 다른 요청이 넣은 video_id

    def table(self, name: str) -> list[dict]:
        return {
            "workers": self.workers,
            "jobs": self.jobs,
            "profiles": self.profiles,
            "worker_heartbeats": self.heartbeats,
            "job_profile_runs": self.runs,
            "candidates": self.candidates,
            "broadcaster_channels": self.broadcasters,
        }[name]


def collect_limit(j: dict) -> int:
    limit = (j.get("params") or {}).get("limit")
    ok = isinstance(limit, int) and not isinstance(limit, bool) and 0 < limit <= 200
    return limit if ok else 200


def _reserve_lookup(db: FakeDB, body: dict) -> httpx.Response:
    """실제 RPC(20261117000011_collect_limits.sql)를 본뜬다."""
    db.lookup_calls.append(body)
    j = next(
        (
            j
            for j in db.jobs
            if j["id"] == body["p_job"]
            and j["workspace_id"] == body["p_workspace"]
            and j["kind"] == "collect"
        ),
        None,
    )
    if j is None:
        return httpx.Response(400, json={"code": "NR003", "message": "x"})
    if j["status"] != "running" or j["claimed_by"] != body["p_worker"] or j["stop_requested"]:
        return httpx.Response(400, json={"code": "NR004", "message": "x"})
    count = j.get("lookup_count", 0)
    if count + body["p_n"] > collect_limit(j):
        return httpx.Response(400, json={"code": "NR005", "message": "x"})
    j["lookup_count"] = count + body["p_n"]
    return httpx.Response(200, json=j["lookup_count"])


def _apply_collect(db: FakeDB, body: dict) -> httpx.Response:
    """실제 RPC(20261117000010_collect_apply.sql)의 검사·동작을 본뜬다."""
    db.apply_calls.append(body)
    j = next(
        (
            j
            for j in db.jobs
            if j["id"] == body["p_job"]
            and j["workspace_id"] == body["p_workspace"]
            and j["kind"] == "collect"
        ),
        None,
    )
    if j is None:
        return httpx.Response(400, json={"code": "NR003", "message": "x"})
    if j["status"] != "running" or j["claimed_by"] != body["p_worker"] or j["stop_requested"]:
        return httpx.Response(400, json={"code": "NR004", "message": "x"})
    if body["p_profile"] not in j["profile_ids"]:
        return httpx.Response(400, json={"code": "NR003", "message": "x"})
    for v in db.race_insert:
        db.candidates.append(
            {"id": str(uuid.uuid4()), "workspace_id": body["p_workspace"], "video_id": v}
        )
    total = sum(r.get("collected_count", 0) for r in db.runs if r["job_id"] == body["p_job"])
    fresh = [
        it
        for it in body["p_payload"]["items"]
        if not any(
            c["workspace_id"] == body["p_workspace"] and c["video_id"] == it["video_id"]
            for c in db.candidates
        )
    ]
    if total + len(fresh) > collect_limit(j):
        return httpx.Response(400, json={"code": "NR005", "message": "x"})
    position = j["profile_ids"].index(body["p_profile"])
    for r in db.runs:
        if r["job_id"] == body["p_job"] and r["status"] == "running" and r["position"] < position:
            r["status"] = "done"
    n = 0
    for it in body["p_payload"]["items"]:
        if any(
            c["workspace_id"] == body["p_workspace"] and c["video_id"] == it["video_id"]
            for c in db.candidates
        ):
            continue
        cid = str(uuid.uuid4())
        db.candidates.append(
            {
                "id": cid,
                "workspace_id": body["p_workspace"],
                "first_job_id": body["p_job"],
                "rep_status": it["status"],
                "rep_profile_id": body["p_profile"],
                **{
                    k: it[k]
                    for k in it
                    if k not in ("status", "reason", "observed_at", "view_count")
                },
            }
        )
        db.observations.append({"candidate_id": cid, "view_count": it["view_count"]})
        db.verdicts.append(
            {
                "candidate_id": cid,
                "profile_id": body["p_profile"],
                "status": it["status"],
                "reason": it["reason"],
            }
        )
        n += 1
    run = next(
        (
            r
            for r in db.runs
            if r["job_id"] == body["p_job"] and r["profile_id"] == body["p_profile"]
        ),
        None,
    )
    if run is None:
        db.runs.append(
            {
                "workspace_id": body["p_workspace"],
                "job_id": body["p_job"],
                "profile_id": body["p_profile"],
                "position": j["profile_ids"].index(body["p_profile"]),
                "collected_count": n,
                "status": "running",
            }
        )
    else:
        run["collected_count"] += n
    return httpx.Response(200, json=n)


def install(router: respx.MockRouter, db: FakeDB) -> None:
    def rest(request: httpx.Request, name: str) -> httpx.Response:
        rows = db.table(name)
        p = _params(request)
        if request.method == "GET":
            return httpx.Response(200, json=_select(rows, p))
        body = json.loads(request.content)
        if request.method == "PATCH":
            hit = [r for r in rows if _match(r, p)]
            for r in hit:
                r.update(body)
            if "return=representation" in request.headers.get("prefer", ""):
                return httpx.Response(200, json=_select(hit, {"select": p.get("select", "*")}))
            return httpx.Response(204)
        # POST upsert(on_conflict)
        keys = p["on_conflict"].split(",")
        for new in body if isinstance(body, list) else [body]:
            cur = next((r for r in rows if all(str(r.get(k)) == str(new[k]) for k in keys)), None)
            if cur is None:
                row = (
                    {"status": "pending", "collected_count": 0}
                    if name == "job_profile_runs"
                    else {}
                )
                row.update(new)
                rows.append(row)
            else:
                cur.update(new)
        return httpx.Response(201)

    for name in (
        "workers",
        "jobs",
        "profiles",
        "worker_heartbeats",
        "job_profile_runs",
        "candidates",
        "broadcaster_channels",
    ):
        router.route(url=f"{REST}/{name}").mock(side_effect=lambda r, n=name: rest(r, n))

    def reserve(request: httpx.Request) -> httpx.Response:
        db.quota_calls += 1
        return httpx.Response(200, json=db.quota_ok)

    def youtube(request: httpx.Request) -> httpx.Response:
        db.youtube_calls.append(request)
        if isinstance(db.youtube_error, Exception):
            raise db.youtube_error
        if db.youtube_error is not None:
            return db.youtube_error
        ids = _params(request)["id"].split(",")
        items = [db.youtube[i] for i in ids if i in db.youtube]
        return httpx.Response(200, json={"items": items})

    router.post(f"{REST}/rpc/reserve_quota").mock(side_effect=reserve)
    router.post(f"{REST}/rpc/reserve_collect_lookup").mock(
        side_effect=lambda r: _reserve_lookup(db, json.loads(r.content))
    )
    router.post(f"{REST}/rpc/apply_collect_batch").mock(
        side_effect=lambda r: _apply_collect(db, json.loads(r.content))
    )
    router.get(VIDEOS_URL).mock(side_effect=youtube)


def _worker(wid: str, ws: str, revoked: bool = False) -> dict:
    return {
        "id": wid,
        "workspace_id": ws,
        "token_hash": hash_secret(SECRET + wid[-2:]),
        "revoked_at": datetime.now(UTC).isoformat() if revoked else None,
    }


@pytest.fixture
def db() -> FakeDB:
    return FakeDB(
        workers=[
            _worker(WORKER_A, WS),
            _worker(WORKER_B, WS),
            _worker(WORKER_OTHER, OTHER_WS),
            _worker(WORKER_REVOKED, WS, revoked=True),
        ],
        profiles=[
            profile(PROFILE_KR, "KR"),
            profile(PROFILE_JP, "JP"),
            profile(PROFILE_OUT, "KR"),
        ],
    )


@pytest.fixture
def api(mock_supabase: respx.MockRouter, db: FakeDB) -> Iterator[TestClient]:
    install(mock_supabase, db)
    app = create_app(make_settings(youtube_api_key=YT_KEY))
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
