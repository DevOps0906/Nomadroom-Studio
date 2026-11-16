"""A-05 단위 테스트용 가짜 PostgREST(메모리).

필터는 eq·in·is·gt만 해석한다. retry·stop RPC는 20261117000012_collect_job_control.sql을 본뜬다.
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


def profile(pid: str, name: str, ws: str = WS, selected: bool = True) -> dict:
    return {"id": pid, "workspace_id": ws, "name": name, "selected": selected}


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
    app = create_app(make_settings())
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def auth(make_token) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token()}"}
