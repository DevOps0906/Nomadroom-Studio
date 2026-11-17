"""A-05 단위 테스트용 가짜 PostgREST(메모리).

필터는 eq·in·is·gt만 해석한다. retry·stop RPC는 20261117000012_collect_job_control.sql을,
검색 수집 RPC(reserve_search_quota·apply_search_batch)는 20261118000013_search_collect.sql을 본뜬다.
YouTube 검색·videos.list는 respx 목(task-019).
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

from app.main import create_app
from app.youtube.client import SEARCH_URL, VIDEOS_URL
from tests.conftest import (
    JWKS_URL,
    OTHER_WORKSPACE_ID,
    SUPABASE_URL,
    WORKSPACE_ID,
    make_settings,
)

REST = f"{SUPABASE_URL}/rest/v1"
WS = str(WORKSPACE_ID)
OTHER_WS = str(OTHER_WORKSPACE_ID)
P1 = "00000000-0000-4000-8000-0000000000a1"
P2 = "00000000-0000-4000-8000-0000000000a2"
P3 = "00000000-0000-4000-8000-0000000000a3"
P4 = "00000000-0000-4000-8000-0000000000a4"
P_OTHER = "00000000-0000-4000-8000-0000000000a9"  # 다른 워크스페이스
JOB = "00000000-0000-4000-8000-0000000000f1"
WORKER = "00000000-0000-4000-8000-0000000000c1"
WORKER_REVOKED = "00000000-0000-4000-8000-0000000000c2"
# Google API 키 형식(AIza + 35자) 가짜 값(런타임 조립)
YT_KEY = "AIza" + "Sy" + "Q" * 31 + "z7"
SEARCH = {"limit": 200, "source": "youtube_search"}

_META = {"select", "limit", "order", "on_conflict"}


def _params(request: httpx.Request) -> dict[str, str]:
    return {k: v[-1] for k, v in parse_qs(request.url.query.decode()).items()}


def _dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


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
        elif op == "gt":
            if cur is None or _dt(str(cur)) <= _dt(value):
                return False
        else:
            raise AssertionError(f"지원하지 않는 필터 {key}={raw}")
    return True


def _select(rows: list[dict], params: dict[str, str]) -> list[dict]:
    out = [r for r in rows if _match(r, params)]
    if params.get("order") == "position.asc":
        out.sort(key=lambda r: r["position"])
    cols = params.get("select")
    if cols and cols != "*":
        out = [{c: r.get(c) for c in cols.split(",")} for r in out]
    return out


def _conflict(name: str) -> httpx.Response:
    return httpx.Response(
        409,
        json={
            "code": "23505",
            "message": f'duplicate key value violates unique constraint "{name}"',
        },
    )


def _rpc_error(code: str) -> httpx.Response:
    return httpx.Response(400, json={"code": code, "message": "x"})


def job(jid: str = JOB, status: str = "queued", **over: Any) -> dict:
    row = {
        "id": jid,
        "workspace_id": WS,
        "kind": "collect",
        "status": status,
        "profile_ids": [P1, P2],
        "params": {"limit": 200},
        "idempotency_key": f"key-{jid[-4:]}",
        "retry_count": 0,
        "stop_requested": False,
        "claimed_by": None,
        "lookup_count": 0,
        "error": None,
        "created_at": "2026-11-01T00:00:00+00:00",
        "started_at": None,
        "finished_at": None,
    }
    row.update(over)
    return row


def run(jid: str, pid: str, position: int, status: str, n: int = 0, **over: Any) -> dict:
    row = {
        "workspace_id": WS,
        "job_id": jid,
        "profile_id": pid,
        "position": position,
        "chrome_state": None,
        "detail": None,
        "status": status,
        "collected_count": n,
    }
    row.update(over)
    return row


@dataclass
class FakeDB:
    profiles: list[dict] = field(default_factory=list)
    jobs: list[dict] = field(default_factory=list)
    runs: list[dict] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)
    workers: list[dict] = field(default_factory=list)
    heartbeats: list[dict] = field(default_factory=list)
    runs_insert_fails: bool = False
    job_insert_conflict: str | None = None  # 강제 23505 제약 이름
    rpc_calls: list[tuple[str, dict]] = field(default_factory=list)
    hide_key_lookups: int = 0  # 멱등 키 조회를 이 횟수만큼 빈 결과로(동시 요청 흉내)
    # --- 검색 수집(task-019) ---
    quota_units: int = 0
    search_units: int = 0
    search_results: list[list[Any]] = field(default_factory=list)  # 검색 호출마다 하나씩 소비
    search_calls: list[dict[str, str]] = field(default_factory=list)
    search_error: httpx.Response | None = None
    search_error_on_call: int = 0  # n번째 검색 호출만 실패(0이면 search_error 항상)
    videos: dict[str, dict] = field(default_factory=dict)  # video_id → videos.list 항목
    video_calls: list[dict[str, str]] = field(default_factory=list)
    videos_error: httpx.Response | None = None
    broadcasters: list[str] = field(default_factory=list)
    observations: list[dict] = field(default_factory=list)
    verdicts: list[dict] = field(default_factory=list)
    apply_calls: list[dict] = field(default_factory=list)
    fail_job_insert: bool = False  # jobs INSERT를 500으로
    fail_retry_patch: bool = False  # 검색 재시도 전이 PATCH(status=eq.failed)를 500으로

    def table(self, name: str) -> list[dict]:
        return {
            "profiles": self.profiles,
            "jobs": self.jobs,
            "job_profile_runs": self.runs,
            "candidates": self.candidates,
            "workers": self.workers,
            "worker_heartbeats": self.heartbeats,
        }[name]

    def _job(self, body: dict) -> dict | None:
        return next(
            (
                j
                for j in self.jobs
                if j["id"] == body["p_job"]
                and j["workspace_id"] == body["p_workspace"]
                and j["kind"] == "collect"
            ),
            None,
        )

    def retry(self, body: dict) -> httpx.Response:
        self.rpc_calls.append(("retry", body))
        j = self._job(body)
        if j is None:
            return _rpc_error("NR003")
        if j["status"] != "failed" or j["retry_count"] >= 3 or j["stop_requested"]:
            return _rpc_error("NR006")
        limit = j["params"].get("limit", 200)
        runs = [r for r in self.runs if r["job_id"] == j["id"]]
        if j["lookup_count"] >= limit or sum(r["collected_count"] for r in runs) >= limit:
            return _rpc_error("NR005")
        if any(
            o["id"] != j["id"]
            and o["workspace_id"] == j["workspace_id"]
            and o["kind"] == "collect"
            and o["status"] in ("queued", "running", "retrying")
            for o in self.jobs
        ):
            return _rpc_error("NR007")
        done = {r["profile_id"] for r in runs if r["status"] == "done"}
        resume = next(((i, p) for i, p in enumerate(j["profile_ids"]) if p not in done), None)
        if resume is None:
            return _rpc_error("NR006")
        for r in runs:
            if r["status"] == "failed" and r["position"] >= resume[0]:
                r["status"] = "pending"
        j.update(
            status="retrying",
            retry_count=j["retry_count"] + 1,
            error=None,
            finished_at=None,
            claimed_by=None,
            params={**j["params"], "resume_from_profile_id": resume[1]},
        )
        return httpx.Response(200, json={"id": j["id"], "status": j["status"]})

    def reserve_search(self, body: dict) -> httpx.Response:
        self.rpc_calls.append(("reserve_search", body))
        n = body["p_units"]
        limit = min(body["p_limit"], 10000)
        search_limit = min(body["p_search_limit"], limit)
        if self.quota_units + n <= limit and self.search_units + n <= search_limit:
            self.quota_units += n
            self.search_units += n
            return httpx.Response(200, json=True)
        return httpx.Response(200, json=False)

    def release_search(self, body: dict) -> httpx.Response:
        self.rpc_calls.append(("release_search", body))
        self.quota_units = max(self.quota_units - body["p_units"], 0)
        self.search_units = max(self.search_units - body["p_units"], 0)
        return httpx.Response(204)

    def reserve(self, body: dict) -> httpx.Response:
        self.rpc_calls.append(("reserve", body))
        if self.quota_units + body["p_units"] <= min(body["p_limit"], 10000):
            self.quota_units += body["p_units"]
            return httpx.Response(200, json=True)
        return httpx.Response(200, json=False)

    def apply_search(self, body: dict) -> httpx.Response:
        self.apply_calls.append(body)
        j = next(
            (
                j
                for j in self.jobs
                if j["id"] == body["p_job"]
                and j["workspace_id"] == body["p_workspace"]
                and (j.get("params") or {}).get("source") == "youtube_search"
            ),
            None,
        )
        if j is None:
            return _rpc_error("NR003")
        if j["status"] != "running" or j["stop_requested"]:
            return _rpc_error("NR004")
        if body["p_profile"] not in j["profile_ids"]:
            return _rpc_error("NR003")
        n = 0
        for item in body["p_payload"]["items"]:
            if any(
                c["workspace_id"] == body["p_workspace"] and c["video_id"] == item["video_id"]
                for c in self.candidates
            ):
                continue
            cid = str(uuid.uuid4())
            self.candidates.append(
                {
                    "id": cid,
                    "workspace_id": body["p_workspace"],
                    "first_job_id": j["id"],
                    "used": False,
                    **{k: v for k, v in item.items() if k != "verdicts"},
                }
            )
            self.observations.append({"candidate_id": cid, "view_count": item["view_count"]})
            self.verdicts.extend({"candidate_id": cid, **v} for v in item["verdicts"])
            n += 1
        pos = j["profile_ids"].index(body["p_profile"])
        r = next(
            (
                x
                for x in self.runs
                if x["job_id"] == j["id"] and x["profile_id"] == body["p_profile"]
            ),
            None,
        )
        if r is None:
            self.runs.append(run(j["id"], body["p_profile"], pos, "done", n))
        else:
            r.update(status="done", collected_count=r["collected_count"] + n)
        return httpx.Response(200, json=n)

    def search(self, request: httpx.Request) -> httpx.Response:
        self.search_calls.append(_params(request))
        n = len(self.search_calls)
        if self.search_error is not None and self.search_error_on_call in (0, n):
            return self.search_error
        ids = self.search_results.pop(0) if self.search_results else []
        items = [
            {"kind": "youtube#searchResult", "id": {"kind": "youtube#video", "videoId": v}}
            for v in ids
        ]
        return httpx.Response(200, json={"items": items})

    def videos_list(self, request: httpx.Request) -> httpx.Response:
        p = _params(request)
        self.video_calls.append(p)
        if self.videos_error is not None:
            return self.videos_error
        items = [self.videos[v] for v in p["id"].split(",") if v in self.videos]
        return httpx.Response(200, json={"items": items})

    def stop(self, body: dict) -> httpx.Response:
        self.rpc_calls.append(("stop", body))
        j = self._job(body)
        if j is None:
            return _rpc_error("NR003")
        if j["status"] in ("queued", "retrying"):
            j.update(status="stopped", error="stopped_by_user", finished_at="now")
        elif j["status"] == "running":
            j["stop_requested"] = True
        else:
            return _rpc_error("NR006")
        return httpx.Response(200, json={"id": j["id"], "status": j["status"]})


def install(router: respx.MockRouter, db: FakeDB) -> None:
    def rest(request: httpx.Request, name: str) -> httpx.Response:
        rows = db.table(name)
        p = _params(request)
        if request.method == "HEAD":
            n = len(_select(rows, p))
            return httpx.Response(200, headers={"content-range": f"*/{n}"})
        if request.method == "GET":
            if name == "jobs" and "idempotency_key" in p and db.hide_key_lookups > 0:
                db.hide_key_lookups -= 1
                return httpx.Response(200, json=[])
            return httpx.Response(200, json=_select(rows, p))
        body = json.loads(request.content)
        if request.method == "PATCH":
            if name == "jobs" and db.fail_retry_patch and p.get("status") == "eq.failed":
                return httpx.Response(500, json={"message": "boom"})
            hit = [r for r in rows if _match(r, p)]
            for r in hit:
                r.update(body)
            if "return=representation" in request.headers.get("prefer", ""):
                return httpx.Response(200, json=_select(hit, {"select": p.get("select", "*")}))
            return httpx.Response(204)
        # POST insert
        if name == "job_profile_runs":
            if db.runs_insert_fails:
                return httpx.Response(500, json={"message": "boom"})
            db.runs.extend(
                {"chrome_state": None, "detail": None, "collected_count": 0, **r} for r in body
            )
            return httpx.Response(201)
        assert name == "jobs"
        if db.fail_job_insert:
            return httpx.Response(500, json={"message": "boom"})
        if db.job_insert_conflict:
            return _conflict(db.job_insert_conflict)
        if any(
            j["workspace_id"] == body["workspace_id"]
            and j["idempotency_key"] == body["idempotency_key"]
            for j in db.jobs
        ):
            return _conflict("jobs_workspace_id_idempotency_key_key")
        if any(
            j["workspace_id"] == body["workspace_id"]
            and j["kind"] == body["kind"]
            and j["status"] in ("queued", "running", "retrying")
            for j in db.jobs
        ):
            return _conflict("jobs_one_active_per_kind_idx")
        new = job(
            str(uuid.uuid4()),
            created_at=datetime.now(UTC).isoformat(),
            requested_by=body.get("requested_by"),
        )
        new.update(body)
        db.jobs.append(new)
        return httpx.Response(201, json=_select([new], {"select": p.get("select", "*")}))

    for name in (
        "profiles",
        "jobs",
        "job_profile_runs",
        "candidates",
        "workers",
        "worker_heartbeats",
    ):
        router.route(url=f"{REST}/{name}").mock(side_effect=lambda r, n=name: rest(r, n))
    router.post(f"{REST}/rpc/retry_collect_job").mock(
        side_effect=lambda r: db.retry(json.loads(r.content))
    )
    router.post(f"{REST}/rpc/stop_collect_job").mock(
        side_effect=lambda r: db.stop(json.loads(r.content))
    )
    router.post(f"{REST}/rpc/reserve_search_quota").mock(
        side_effect=lambda r: db.reserve_search(json.loads(r.content))
    )
    router.post(f"{REST}/rpc/release_search_quota").mock(
        side_effect=lambda r: db.release_search(json.loads(r.content))
    )
    router.post(f"{REST}/rpc/reserve_quota").mock(
        side_effect=lambda r: db.reserve(json.loads(r.content))
    )
    router.post(f"{REST}/rpc/apply_search_batch").mock(
        side_effect=lambda r: db.apply_search(json.loads(r.content))
    )
    router.get(f"{REST}/broadcaster_channels").mock(
        side_effect=lambda r: httpx.Response(200, json=[{"channel_id": c} for c in db.broadcasters])
    )
    router.get(SEARCH_URL).mock(side_effect=db.search)
    router.get(VIDEOS_URL).mock(side_effect=db.videos_list)


def yt_video(
    vid: str,
    views: int = 1000,
    duration: str = "PT10M",
    title: str = "영상",
    license: str = "youtube",
    channel: str = "UC" + "c" * 22,
) -> dict:
    return {
        "kind": "youtube#video",
        "id": vid,
        "snippet": {"channelId": channel, "channelTitle": "채널", "title": title},
        "statistics": {"viewCount": str(views)},
        "status": {"license": license},
        "contentDetails": {"duration": duration},
    }


def profile(pid: str, name: str, ws: str = WS, selected: bool = True, **over: Any) -> dict:
    row = {
        "id": pid,
        "workspace_id": ws,
        "name": name,
        "market": "KR",
        "format": "all",
        "category": None,
        "min_views": 0,
        "max_growth_pct": 5,
        "keywords": [],
        "cc_only": False,
        "include_broadcast": True,
        "selected": selected,
        "updated_at": "2026-11-01T00:00:00+00:00",
    }
    row.update(over)
    return row


@pytest.fixture
def db() -> FakeDB:
    return FakeDB(
        profiles=[
            profile(P1, "가"),
            profile(P2, "나"),
            profile(P3, "다", selected=False),
            profile(P4, "라", selected=False),
            profile(P_OTHER, "타", ws=OTHER_WS),
        ],
        workers=[
            {"id": WORKER, "workspace_id": WS, "revoked_at": None},
            {"id": WORKER_REVOKED, "workspace_id": WS, "revoked_at": "2026-11-01T00:00:00Z"},
        ],
    )


@pytest.fixture
def api(mock_supabase: respx.MockRouter, jwks_payload: dict, db: FakeDB) -> Iterator[TestClient]:
    mock_supabase.get(JWKS_URL).mock(return_value=httpx.Response(200, json=jwks_payload))
    mock_supabase.get(f"{REST}/workspace_members").mock(
        return_value=httpx.Response(200, json=[{"workspace_id": WS}])
    )
    install(mock_supabase, db)
    app = create_app(make_settings(youtube_api_key=YT_KEY))
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def auth(make_token) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token()}"}
