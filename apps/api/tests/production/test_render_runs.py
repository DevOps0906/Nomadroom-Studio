"""task-023 렌더 요청·재시도(A-15·A-16)·오프라인 만료(E3) 단위 테스트.

가짜 PostgREST(메모리)·Storage는 test_jobs_api의 FakeDB를 잇고, RPC(request_render_run·
retry_render_run·claim_production_task·finish_production_task·expire_production_offline)는
supabase/migrations/20261119000017_production_render.sql을 본뜬다(실제 SQL은 pgTAP이 검사).
test_worker_production.py가 이 파일의 ProdDB·install_prod를 재사용한다.
"""

import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.auth.worker import format_token, hash_secret
from app.main import create_app
from tests.conftest import JWKS_URL, make_settings
from tests.production.test_jobs_api import (
    OTHER_WS,
    REST,
    STORAGE,
    URL,
    USER,
    WS,
    FakeDB,
    _params,
    _select,
)

WORKER_A = "00000000-0000-4000-8000-0000000000c1"
WORKER_B = "00000000-0000-4000-8000-0000000000c2"
WORKER_OTHER = "00000000-0000-4000-8000-0000000000c3"  # 다른 워크스페이스
SECRET = "prod-worker-secret-value-for-tests-0001"
OFFLINE = timedelta(minutes=3)
QUEUED_STALE = timedelta(minutes=10)


def wtoken(worker_id: str) -> str:
    return format_token(uuid.UUID(worker_id), SECRET + worker_id[-2:])


def wauth(worker_id: str = WORKER_A) -> dict[str, str]:
    return {"Authorization": f"Bearer {wtoken(worker_id)}"}


def iso(dt: datetime) -> str:
    return dt.isoformat()


def ago(**kw: float) -> str:
    return iso(datetime.now(UTC) - timedelta(**kw))


def ts(v: Any) -> datetime | None:
    return datetime.fromisoformat(v) if isinstance(v, str) else None


def _err(code: str, message: str = "x") -> httpx.Response:
    return httpx.Response(400, json={"code": code, "message": message})


def _state(status: str) -> httpx.Response:
    return _err("NR010", f"현재 상태({status})에서는 할 수 없습니다.")


@dataclass
class ProdDB(FakeDB):
    def add_run(self, job: dict, rev: dict, status: str = "queued", **over: Any) -> dict:
        run = {
            "id": str(uuid.uuid4()),
            "workspace_id": job["workspace_id"],
            "job_id": job["id"],
            "revision_id": rev["id"],
            "lang": "ko",
            "attempt": 1,
            "retry_of": None,
            "idempotency_key": f"rk-{uuid.uuid4().hex[:8]}",
            "preset_version": job["preset_version"],
            "status": status,
            "progress_pct": 0,
            "progress_stage": None,
            "error_stage": None,
            "error_code": None,
            "claimed_by": None,
            "mp4_asset_id": None,
            "report_asset_id": None,
            "hook_audio_asset_id": None,
            "requested_by": USER,
            "created_at": ago(minutes=5),
            "started_at": None,
            "finished_at": None,
            "updated_at": ago(minutes=5),
        }
        run.update(over)
        self.runs.append(run)
        return run

    def job(self, jid: str) -> dict:
        return next(j for j in self.jobs if j["id"] == jid)

    # --- RPC(000017 본뜸) ---
    def expire(self, ws: str) -> dict:
        now = datetime.now(UTC)
        runs: list[str] = []
        jobs: list[str] = []
        for r in self.runs:
            if r["workspace_id"] != ws:
                continue
            seen = max(t for t in (ts(r["updated_at"]), ts(r["started_at"])) if t)
            running = r["status"] == "running" and seen < now - OFFLINE
            queued = r["status"] == "queued" and ts(r["created_at"]) < now - QUEUED_STALE
            if running or queued:
                r.update(
                    status="failed",
                    error_stage="render",
                    error_code="worker_offline",
                    finished_at=iso(now),
                    updated_at=iso(now),
                )
                runs.append(r["id"])
                j = self.job(r["job_id"])
                if r["lang"] == "ko" and j["status"] == "rendering":
                    j.update(
                        status="failed",
                        failed_stage="render",
                        error_code="worker_offline",
                        updated_at=iso(now),
                    )
        for j in self.jobs:
            if (
                j["workspace_id"] == ws
                and j["status"] == "preparing"
                and j["claimed_by"]
                and ts(j["updated_at"]) < now - OFFLINE
            ):
                j.update(
                    status="failed",
                    failed_stage="prepare",
                    error_code="worker_offline",
                    updated_at=iso(now),
                )
                jobs.append(j["id"])
        gone = [
            a
            for a in self.assets
            if a["workspace_id"] == ws
            and a["status"] == "pending"
            and (
                a["render_run_id"] in runs
                or (
                    a["job_id"] in jobs
                    and a["render_run_id"] is None
                    and a["kind"] in ("source", "analysis", "sheet")
                )
            )
        ]
        for a in gone:
            self.assets.remove(a)
        return {
            "expired": len(runs) + len(jobs),
            "deleted_paths": [a["storage_path"] for a in gone],
        }

    def _run_json(self, run: dict, created: bool) -> httpx.Response:
        keys = ("id", "job_id", "revision_id", "lang", "status", "attempt", "retry_of")
        out = {k: run[k] for k in keys}
        out.update(preset_version=run["preset_version"], created=created)
        return httpx.Response(200, json=out)

    def _ws_job(self, ws: str, jid: str) -> dict | None:
        return next((j for j in self.jobs if j["id"] == jid and j["workspace_id"] == ws), None)

    def request_run(self, b: dict) -> httpx.Response:
        self.rpc_calls.append("request")
        ws = b["p_workspace"]
        j = self._ws_job(ws, b["p_job"])
        if j is None:
            return _err("NR009")
        hit = next(
            (
                r
                for r in self.runs
                if r["workspace_id"] == ws and r["idempotency_key"] == b["p_key"]
            ),
            None,
        )
        if hit is not None:
            return _err("NR011") if hit["job_id"] != j["id"] else self._run_json(hit, False)
        ja = b["p_lang"] == "ja"  # 000028: ja는 inspect·done, 현재 승인 ja·파생 원본 = 현재 승인 ko
        if j["status"] not in (("inspect", "done") if ja else ("review",)):
            return _state(j["status"])
        rev = next(
            (r for r in self.revisions if r["id"] == b["p_revision"] and r["job_id"] == j["id"]),
            None,
        )
        current = j.get("current_ja_revision_id") if ja else j["current_revision_id"]
        if (
            rev is None
            or rev["approved_at"] is None
            or rev["lang"] != b["p_lang"]
            or rev["id"] != current
        ):
            return _err("NR012")
        if ja:
            ko = next((r for r in self.revisions if r["id"] == j["current_revision_id"]), None)
            if (
                rev.get("derived_from") != j["current_revision_id"]
                or ko is None
                or (ko["approved_at"] is None)
            ):
                return _err("NR010", "원본(ko) 편집안이 바뀌었습니다. 일본어판을 다시 만드세요.")
        if any(
            r["workspace_id"] == ws and r["status"] in ("queued", "running") for r in self.runs
        ) or any(
            r["job_id"] == j["id"]
            and r["revision_id"] == rev["id"]
            and r["lang"] == b["p_lang"]
            and r["status"] in ("queued", "running", "done")
            for r in self.runs
        ):
            return _err("NR014")
        cut = datetime.now(UTC) - timedelta(seconds=60)
        if any(r["workspace_id"] == ws and ts(r["created_at"]) > cut for r in self.runs):
            return _err("NR013")
        run = self.add_run(
            j,
            rev,
            idempotency_key=b["p_key"],
            requested_by=b["p_user"],
            lang=b["p_lang"],
            created_at=iso(datetime.now(UTC)),
            updated_at=iso(datetime.now(UTC)),
        )
        if not ja:
            j.update(
                status="rendering", failed_stage=None, error_code=None, updated_at=run["created_at"]
            )
        return self._run_json(run, True)

    def retry_run(self, b: dict) -> httpx.Response:
        self.rpc_calls.append("retry")
        ws = b["p_workspace"]
        j = self._ws_job(ws, b["p_job"])
        if j is None:
            return _err("NR009")
        old = next(
            (
                r
                for r in self.runs
                if r["id"] == b["p_run"] and r["job_id"] == j["id"] and r["workspace_id"] == ws
            ),
            None,
        )
        if old is None:
            return _err("NR009")
        if old["lang"] != "ko":  # 000028 K3
            return _err("NR010", "일본어판 렌더는 다시 렌더 요청하세요.")
        if (
            old["status"] != "failed"
            or old["error_code"] in ("hook_too_long", "text_too_long", "tts_failed")
            or j["status"] != "failed"
            or j["failed_stage"] not in ("audio", "render")
            or old["revision_id"] != j["current_revision_id"]
        ):
            return _state(j["status"])
        chain = [
            r
            for r in self.runs
            if r["job_id"] == j["id"]
            and r["revision_id"] == old["revision_id"]
            and r["lang"] == old["lang"]
        ]
        latest = max(chain, key=lambda r: (r["created_at"], r["attempt"]))
        if latest["id"] != old["id"]:
            return _state(j["status"])
        attempt = max(r["attempt"] for r in chain) + 1
        if attempt > 3:
            return _err("NR015")
        if any(r["workspace_id"] == ws and r["status"] in ("queued", "running") for r in self.runs):
            return _err("NR014")
        rev = next(r for r in self.revisions if r["id"] == old["revision_id"])
        now = iso(datetime.now(UTC))
        run = self.add_run(
            j,
            rev,
            attempt=attempt,
            retry_of=old["id"],
            idempotency_key=f"retry:{old['id']}",
            lang=old["lang"],
            created_at=now,
            updated_at=now,
        )
        j.update(status="rendering", failed_stage=None, error_code=None, updated_at=now)
        return self._run_json(run, True)

    def claim(self, b: dict) -> httpx.Response:
        self.rpc_calls.append("claim")
        ws, worker = b["p_workspace"], b["p_worker"]
        shop_ok = "shopping" in (b.get("p_formats") or [])  # 000024 R4: 지원 워커만 쇼핑
        ja_ok = "ja" in (b.get("p_formats") or [])  # 000028 K8: ja 알린 워커만 ja run
        now = iso(datetime.now(UTC))
        run = next(
            (
                r
                for r in self.runs
                if r["workspace_id"] == ws
                and r["claimed_by"] == worker
                and r["status"] == "running"
            ),
            None,
        )
        job = None
        if run is None:
            job = next(
                (
                    j
                    for j in self.jobs
                    if j["workspace_id"] == ws
                    and j["claimed_by"] == worker
                    and j["status"] == "preparing"
                ),
                None,
            )
        if run is None and job is None:
            jobs = sorted(
                (
                    j
                    for j in self.jobs
                    if j["workspace_id"] == ws
                    and j["status"] == "preparing"
                    and not j["claimed_by"]
                    and (shop_ok or j.get("kind") != "shopping")
                ),
                key=lambda j: j["created_at"],
            )
            queued = sorted(
                (
                    r
                    for r in self.runs
                    if r["workspace_id"] == ws
                    and r["status"] == "queued"
                    and (ja_ok or r["lang"] != "ja")
                    and (shop_ok or self.job(r["job_id"]).get("kind") != "shopping")
                ),
                key=lambda r: r["created_at"],
            )
            if jobs and (not queued or jobs[0]["created_at"] <= queued[0]["created_at"]):
                job = jobs[0]
            elif queued:
                run = queued[0]
            else:
                return httpx.Response(
                    200, content=b"null", headers={"content-type": "application/json"}
                )
        if run is not None:
            run.update(
                status="running",
                claimed_by=worker,
                started_at=run["started_at"] or now,
                updated_at=now,
            )
            job = self.job(run["job_id"])
            rev = next(r for r in self.revisions if r["id"] == run["revision_id"])
        else:
            assert job is not None
            job.update(claimed_by=worker, updated_at=now)
        render = run is not None
        return httpx.Response(
            200,
            json={
                "kind": "render" if render else "prepare",
                "id": run["id"] if render else job["id"],
                "job_id": job["id"],
                "job_kind": job.get("kind", "general"),
                "format": job["format"],
                "preset_version": run["preset_version"] if render else job["preset_version"],
                "lang": run["lang"] if render else None,
                "source_start_sec": job["source_start_sec"],
                "segment_len_sec": job["segment_len_sec"],
                "source_kind": job["source_kind"],
                "spec": rev["spec"] if render else None,
            },
        )

    def finish(self, b: dict) -> httpx.Response:
        self.rpc_calls.append("finish")
        ws, worker, kind = b["p_workspace"], b["p_worker"], b["p_kind"]
        run = None
        if kind == "prepare":
            j = self._ws_job(ws, b["p_task"])
            if j is None:
                return _err("NR009")
            if j["claimed_by"] != worker or j["status"] != "preparing":
                return _state(j["status"])
            allowed = ("source", "analysis", "sheet")
        else:
            run = next(
                (r for r in self.runs if r["id"] == b["p_task"] and r["workspace_id"] == ws), None
            )
            if run is None:
                return _err("NR009")
            j = self.job(run["job_id"])
            if run["claimed_by"] != worker or run["status"] != "running":
                return _state(run["status"])
            allowed = ("output_mp4", "report", "hook_audio")
        run_id = run["id"] if run else None
        ids = set(b["p_asset_ids"] or [])
        listed = [
            a
            for a in self.assets
            if a["id"] in ids
            and a["job_id"] == j["id"]
            and a["status"] == "pending"
            and a["kind"] in allowed
            and a["created_by"] == worker
            and a["render_run_id"] == run_id
        ]
        now = iso(datetime.now(UTC))
        if b["p_status"] == "done":
            kinds = [a["kind"] for a in listed]
            if len(listed) != len(ids):
                return _err("NR012")
            if kind == "prepare" and j.get("kind") == "shopping":
                # 000023 P3: ready 원본마다 source·analysis 1건·sheet ≥1, 모든 산출물에 parent
                ready = [
                    a["id"]
                    for a in self.assets
                    if a["job_id"] == j["id"]
                    and a["kind"] == "source_upload"
                    and a["status"] == "ready"
                ]
                groups: dict[str, list[str]] = {u: [] for u in ready}
                for a in listed:
                    if a.get("parent_asset_id") not in groups:
                        return _err("NR012")
                    groups[a["parent_asset_id"]].append(a["kind"])
                if not groups or any(
                    g.count("source") != 1 or g.count("analysis") != 1 or "sheet" not in g
                    for g in groups.values()
                ):
                    return _err("NR012")
            elif kind == "prepare" and (
                kinds.count("source") != 1 or kinds.count("analysis") != 1 or "sheet" not in kinds
            ):
                return _err("NR012")
            if kind == "render" and (
                kinds.count("output_mp4") != 1
                or kinds.count("report") != 1
                or kinds.count("hook_audio") > 1
            ):
                return _err("NR012")
            for a in listed:
                a["status"] = "ready"
        gone = [
            a
            for a in self.assets
            if a["job_id"] == j["id"]
            and a["status"] == "pending"
            and a["kind"] in allowed
            and a["render_run_id"] == run_id
            and a["id"] not in ids
        ]
        for a in gone:
            self.assets.remove(a)
        if kind == "prepare":
            if b["p_status"] == "done":
                if not j["current_revision_id"]:
                    self.add_revision(j, spec=b["p_spec"], validation=b["p_validation"])
                j.update(
                    status="review", source_meta=b["p_meta"] or j["source_meta"], updated_at=now
                )
            else:
                j.update(
                    status="failed",
                    failed_stage="prepare",
                    error_code=b["p_error_code"],
                    updated_at=now,
                )
        else:
            assert run is not None
            if b["p_status"] == "done":
                by_kind = {a["kind"]: a["id"] for a in listed}
                run.update(
                    status="done",
                    progress_pct=100,
                    finished_at=now,
                    updated_at=now,
                    mp4_asset_id=by_kind.get("output_mp4"),
                    report_asset_id=by_kind.get("report"),
                    hook_audio_asset_id=by_kind.get("hook_audio"),
                )
                if run["lang"] == "ko" and j["status"] == "rendering":
                    j.update(status="inspect", updated_at=now)
            else:
                run.update(
                    status="failed",
                    error_stage=b["p_error_stage"],
                    error_code=b["p_error_code"],
                    finished_at=now,
                    updated_at=now,
                )
                if run["lang"] == "ko" and j["status"] == "rendering":
                    if b["p_error_code"] in ("hook_too_long", "text_too_long", "tts_failed"):
                        j.update(
                            status="review", failed_stage=None, error_code=None, updated_at=now
                        )
                    else:
                        j.update(
                            status="failed",
                            failed_stage=b["p_error_stage"],
                            error_code=b["p_error_code"],
                            updated_at=now,
                        )
        paths = [a["storage_path"] for a in gone]
        return httpx.Response(200, json={"status": b["p_status"], "deleted_paths": paths})


def install_prod(router: respx.MockRouter, db: ProdDB) -> None:
    def rest(request: httpx.Request, name: str) -> httpx.Response:
        rows = db.table(name)
        p = _params(request)
        if request.method == "GET":
            return httpx.Response(200, json=_select(rows, p))
        sel = {"select": p.get("select", "*")}
        if request.method == "DELETE":
            hit = [r for r in rows if _select([r], {k: v for k, v in p.items() if k != "select"})]
            for r in hit:
                rows.remove(r)
            return httpx.Response(200, json=_select(hit, sel))
        body = json.loads(request.content)
        if request.method == "PATCH":
            hit = [r for r in rows if _select([r], {k: v for k, v in p.items() if k != "select"})]
            for r in hit:
                r.update(body)
            return httpx.Response(200, json=_select(hit, sel))
        items = body if isinstance(body, list) else [body]
        if name == "worker_heartbeats":  # upsert(on_conflict=worker_id)
            for it in items:
                cur = next((h for h in rows if h["worker_id"] == it["worker_id"]), None)
                if cur is None:
                    rows.append(dict(it))
                else:
                    cur.update(it)
            return httpx.Response(201)
        assert name == "production_assets"
        new = [
            {
                "duration_sec": None,
                "render_run_id": None,
                "created_at": iso(datetime.now(UTC)),
                **it,
            }
            for it in items
        ]
        rows.extend(new)
        return httpx.Response(201, json=_select(new, sel))

    for name in (
        "production_jobs",
        "production_assets",
        "edit_revisions",
        "render_runs",
        "candidates",
        "workers",
        "worker_heartbeats",
    ):
        router.route(url=f"{REST}/{name}").mock(side_effect=lambda r, n=name: rest(r, n))
    rpcs = {
        "expire_production_offline": lambda b: httpx.Response(
            200, json=db.expire(b["p_workspace"])
        ),
        "request_render_run": db.request_run,
        "retry_render_run": db.retry_run,
        "claim_production_task": db.claim,
        "finish_production_task": db.finish,
    }
    for name, fn in rpcs.items():
        router.post(f"{REST}/rpc/{name}").mock(side_effect=lambda r, f=fn: f(json.loads(r.content)))
    router.post(url__startswith=f"{STORAGE}/object/upload/sign/production/").mock(
        side_effect=db.sign_upload
    )
    router.post(url__startswith=f"{STORAGE}/object/sign/production/").mock(
        side_effect=db.sign_download
    )
    router.get(url__startswith=f"{STORAGE}/object/info/production/").mock(side_effect=db.info)
    router.delete(url__startswith=f"{STORAGE}/object/production/").mock(side_effect=db.delete)


def _worker_row(wid: str, ws: str) -> dict:
    return {
        "id": wid,
        "workspace_id": ws,
        "token_hash": hash_secret(SECRET + wid[-2:]),
        "revoked_at": None,
    }


@pytest.fixture
def db() -> ProdDB:
    return ProdDB(
        workers=[
            _worker_row(WORKER_A, WS),
            _worker_row(WORKER_B, WS),
            _worker_row(WORKER_OTHER, OTHER_WS),
        ],
    )


@pytest.fixture
def api(mock_supabase: respx.MockRouter, jwks_payload: dict, db: ProdDB) -> Iterator[TestClient]:
    mock_supabase.get(JWKS_URL).mock(return_value=httpx.Response(200, json=jwks_payload))
    mock_supabase.get(f"{REST}/workspace_members").mock(
        return_value=httpx.Response(200, json=[{"workspace_id": WS}])
    )
    install_prod(mock_supabase, db)
    app = create_app(make_settings())
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def auth(make_token) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token()}"}


def review_job(db: ProdDB, ws: str = WS, approved: bool = True) -> tuple[dict, dict]:
    job = db.add_job(ws=ws, status="review")
    rev = db.add_revision(job, approved=approved)
    return job, rev


def render(api: TestClient, auth: dict, job: dict, rev: dict, key: str = "rk-1", **over: Any):
    body = {"revision_id": rev["id"], "lang": "ko", **over}
    return api.post(
        f"{URL}/{job['id']}/render-runs", json=body, headers={**auth, "Idempotency-Key": key}
    )


def failed_render_job(db: ProdDB, code: str = "render_failed", stage: str = "render", **run_over):
    job = db.add_job(status="failed", failed_stage=stage, error_code=code)
    rev = db.add_revision(job, approved=True)
    run = db.add_run(job, rev, status="failed", error_stage=stage, error_code=code, **run_over)
    return job, rev, run


def retry(api: TestClient, auth: dict, job: dict, run: dict) -> httpx.Response:
    return api.post(f"{URL}/{job['id']}/render-runs/{run['id']}/retry", headers=auth)


# === A-15 렌더 요청 ==============================================================


def test_a15_creates_queued_run_and_moves_job_to_rendering(api, auth, db):
    job, rev = review_job(db)
    r = render(api, auth, job, rev)
    assert r.status_code == 202
    run = r.json()["render_run"]
    assert run["status"] == "queued" and run["attempt"] == 1 and run["lang"] == "ko"
    assert run["preset_version"] == "category-1080-v1" and run["revision_id"] == rev["id"]
    assert db.job(job["id"])["status"] == "rendering"
    assert db.runs[0]["idempotency_key"] == "rk-1" and db.runs[0]["requested_by"] == USER


def test_a15_same_key_returns_200_existing_run(api, auth, db):
    job, rev = review_job(db)
    first = render(api, auth, job, rev).json()["render_run"]
    again = render(api, auth, job, rev)  # job은 이미 rendering이어도 같은 키는 기존 run
    assert again.status_code == 200
    assert again.json()["render_run"]["id"] == first["id"]
    assert len(db.runs) == 1


def test_e8_key_used_by_other_job_is_409(api, auth, db):
    job, rev = review_job(db)
    render(api, auth, job, rev, key="shared")
    other, other_rev = review_job(db)
    r = render(api, auth, other, other_rev, key="shared")
    assert r.status_code == 409 and r.json()["field"] == "Idempotency-Key"


def ja_job(db: ProdDB, status: str = "inspect", fmt: str = "category") -> tuple[dict, dict, dict]:
    """task-050: 승인 ko(현재)와 그 ko에서 파생·승인된 현재 ja."""
    job = db.add_job(status=status, format=fmt)
    ko = db.add_revision(job, approved=True)
    ja = db.add_revision(job, approved=True, lang="ja", derived_from=ko["id"])
    job["current_ja_revision_id"] = ja["id"]
    job["current_revision_id"] = ko["id"]
    return job, ko, ja


@pytest.mark.parametrize("status", ["inspect", "done"])
def test_k2_ja_render_keeps_job_status(api, auth, db, status):
    job, _, ja = ja_job(db, status)
    r = render(api, auth, job, ja, lang="ja")
    assert r.status_code == 202
    run = r.json()["render_run"]
    assert run["lang"] == "ja" and run["revision_id"] == ja["id"] and run["status"] == "queued"
    assert db.job(job["id"])["status"] == status  # ja는 job 상태를 바꾸지 않는다


def test_k2_ja_render_in_review_is_409(api, auth, db):
    job, _, ja = ja_job(db, "review")
    r = render(api, auth, job, ja, lang="ja")
    assert r.status_code == 409 and "review" in r.json()["message"]
    assert db.runs == []


def test_k2_ja_render_source_changed_is_409(api, auth, db):
    job, ko, ja = ja_job(db)
    newer = db.add_revision(job, approved=True)  # ko가 새로 승인됨 → ja 파생 원본이 현재 아님
    job["current_revision_id"] = newer["id"]
    r = render(api, auth, job, ja, lang="ja")
    assert r.status_code == 409 and "원본(ko)" in r.json()["message"]
    assert db.runs == [] and ko["id"] != newer["id"]


def test_k2_ja_lang_with_ko_revision_is_400(api, auth, db):
    job, ko, _ = ja_job(db)
    r = render(api, auth, job, ko, lang="ja")
    assert r.status_code == 400 and db.runs == []


def test_task051_variety_ja_is_202(api, auth, db):  # task-051: 예능형 일본어 더빙 렌더 허용
    job, _, ja = ja_job(db, fmt="variety")
    r = render(api, auth, job, ja, lang="ja")
    assert r.status_code == 202
    run = r.json()["render_run"]
    assert run["lang"] == "ja" and run["revision_id"] == ja["id"]
    assert db.job(job["id"])["status"] == "inspect"


def test_k3_ja_retry_is_409(api, auth, db):
    job, _, ja = ja_job(db)
    run = db.add_run(job, ja, status="failed", error_stage="render", error_code="render_failed")
    run["lang"] = "ja"
    r = retry(api, auth, job, run)
    assert r.status_code == 409 and "다시 렌더 요청" in r.json()["message"]
    assert len(db.runs) == 1 and db.job(job["id"])["status"] == "inspect"


def test_a15_concurrent_second_render_in_workspace_is_409(api, auth, db):
    job, rev = review_job(db)
    assert render(api, auth, job, rev, key="a").status_code == 202
    other, other_rev = review_job(db)
    r = render(api, auth, other, other_rev, key="b")
    assert r.status_code == 409
    assert r.json()["message"] == "진행 중이거나 완료된 렌더가 있습니다."
    assert db.job(other["id"])["status"] == "review"


def test_a15_same_revision_done_run_is_409(api, auth, db):
    job, rev = review_job(db)
    db.add_run(job, rev, status="done", created_at=ago(hours=1))
    assert render(api, auth, job, rev).status_code == 409


def test_a15_new_key_within_60s_is_429(api, auth, db):
    finished, frev = review_job(db)
    db.add_run(finished, frev, status="failed", created_at=ago(seconds=10))
    job, rev = review_job(db)
    r = render(api, auth, job, rev, key="new")
    assert r.status_code == 429 and r.json()["code"] == "RATE_LIMITED"


def test_a15_unapproved_or_not_current_revision_is_400(api, auth, db):
    job, rev = review_job(db, approved=False)
    r = render(api, auth, job, rev)
    assert r.status_code == 400 and r.json()["field"] == "revision_id"
    old = db.add_revision(job, rev_no=2, approved=True)
    db.add_revision(job, rev_no=3, approved=True)  # current는 rev3
    assert render(api, auth, job, old, key="k2").status_code == 400


def test_a15_job_not_review_is_409_with_status(api, auth, db):
    job, rev = review_job(db)
    job["status"] = "inspect"
    r = render(api, auth, job, rev)
    assert r.status_code == 409 and "inspect" in r.json()["message"]


def test_a15_other_workspace_job_is_404_and_key_required(api, auth, db):
    job, rev = review_job(db, ws=OTHER_WS)
    assert render(api, auth, job, rev).status_code == 404
    mine, mrev = review_job(db)
    r = api.post(
        f"{URL}/{mine['id']}/render-runs",
        json={"revision_id": mrev["id"], "lang": "ko"},
        headers=auth,
    )
    assert r.status_code == 400 and r.json()["field"] == "Idempotency-Key"


# === A-16 재시도(E5) ============================================================


def test_a16_retry_creates_new_run_attempt_plus_one(api, auth, db):
    job, rev, run = failed_render_job(db)
    r = retry(api, auth, job, run)
    assert r.status_code == 202
    new = r.json()["render_run"]
    assert new["attempt"] == 2 and new["retry_of"] == run["id"] and new["revision_id"] == rev["id"]
    assert new["status"] == "queued" and new["id"] != run["id"]
    assert run["status"] == "failed"  # 이전 run·자산은 그대로(덮어쓰기 없음)
    j = db.job(job["id"])
    assert j["status"] == "rendering" and j["failed_stage"] is None and j["error_code"] is None


def test_e5_retry_only_latest_failed_run_of_current_revision(api, auth, db):
    job, rev, run = failed_render_job(db, created_at=ago(minutes=30))
    newer = db.add_run(job, rev, status="failed", attempt=2, created_at=ago(minutes=20))
    assert retry(api, auth, job, run).status_code == 409  # 최신 아님
    assert retry(api, auth, job, newer).json()["render_run"]["attempt"] == 3


def test_e5_retry_cap_three_attempts(api, auth, db):
    job, rev, run = failed_render_job(db, attempt=3)
    r = retry(api, auth, job, run)
    assert r.status_code == 409 and r.json()["message"] == "재시도 횟수를 넘었습니다."


@pytest.mark.parametrize("code", ["hook_too_long", "text_too_long", "tts_failed"])
def test_e5_retry_rejects_review_return_codes(api, auth, db, code):
    job, rev, run = failed_render_job(db, code=code)
    assert retry(api, auth, job, run).status_code == 409


def test_e5_retry_rejects_prepare_stage_and_non_failed_run(api, auth, db):
    job = db.add_job(status="failed", failed_stage="prepare", error_code="download_failed")
    rev = db.add_revision(job, approved=True)
    run = db.add_run(job, rev, status="failed", error_stage="render", error_code="render_failed")
    assert retry(api, auth, job, run).status_code == 409
    job2, rev2, run2 = failed_render_job(db)
    run2["status"] = "done"
    assert retry(api, auth, job2, run2).status_code == 409


def test_e5_retry_rejects_run_of_old_revision(api, auth, db):
    job, rev, run = failed_render_job(db)
    db.add_revision(job, rev_no=2, approved=True)  # 현재 리비전이 바뀜
    assert retry(api, auth, job, run).status_code == 409


def test_a16_other_workspace_or_unknown_run_is_404(api, auth, db):
    job = db.add_job(ws=OTHER_WS, status="failed", failed_stage="render")
    rev = db.add_revision(job, approved=True)
    run = db.add_run(job, rev, status="failed", error_stage="render", error_code="render_failed")
    assert retry(api, auth, job, run).status_code == 404
    mine, _, _ = failed_render_job(db)
    assert retry(api, auth, mine, {"id": str(uuid.uuid4())}).status_code == 404


def test_e10_audio_missing_recovers_by_hook_upload_then_retry(api, auth, db):
    job, rev, run = failed_render_job(db, code="audio_missing", stage="audio")
    up = api.post(
        f"{URL}/{job['id']}/uploads",
        json={"kind": "hook_audio", "size_bytes": 10, "mime": "audio/wav"},
        headers=auth,
    )
    assert up.status_code == 201
    r = retry(api, auth, job, run)
    assert r.status_code == 202 and r.json()["render_run"]["attempt"] == 2


# === E3 오프라인 지연 평가(A-09 GET·A-15·A-16) ====================================


def test_e3_get_detail_expires_running_run_after_3_minutes(api, auth, db):
    job = db.add_job(status="rendering")
    rev = db.add_revision(job, approved=True)
    run = db.add_run(
        job,
        rev,
        status="running",
        claimed_by=WORKER_A,
        started_at=ago(minutes=10),
        updated_at=ago(minutes=4),
    )
    r = api.get(f"{URL}/{job['id']}", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body["job"]["status"] == "failed" and body["job"]["error_code"] == "worker_offline"
    assert body["latest_run"]["error_code"] == "worker_offline"
    assert run["error_stage"] == "render"


def test_e3_fresh_progress_keeps_run_running(api, auth, db):
    job = db.add_job(status="rendering")
    rev = db.add_revision(job, approved=True)
    db.add_run(job, rev, status="running", started_at=ago(minutes=10), updated_at=ago(minutes=1))
    assert api.get(f"{URL}/{job['id']}", headers=auth).json()["job"]["status"] == "rendering"


def test_e3_unclaimed_queued_run_fails_after_10_minutes_and_unlocks_workspace(api, auth, db):
    stuck = db.add_job(status="rendering")
    srev = db.add_revision(stuck, approved=True)
    db.add_run(stuck, srev, status="queued", created_at=ago(minutes=11))
    job, rev = review_job(db)
    r = render(api, auth, job, rev)  # A-15가 먼저 만료시켜 잠금이 풀린다
    assert r.status_code == 202
    assert db.job(stuck["id"])["status"] == "failed"
    assert db.job(stuck["id"])["error_code"] == "worker_offline"


def test_e3_claimed_preparing_job_fails_after_3_minutes_in_list(api, auth, db):
    job = db.add_job(status="preparing", claimed_by=WORKER_A, updated_at=ago(minutes=4))
    items = api.get(URL, headers=auth).json()["items"]
    assert items[0]["status"] == "failed" and items[0]["failed_stage"] == "prepare"
    assert db.job(job["id"])["error_code"] == "worker_offline"


# === 리뷰 반영 6: null이 재시도 판정을 우회하지 않는다 ==============================


def test_review6_retry_with_null_error_code_and_failed_stage_is_409(api, auth, db):
    job = db.add_job(status="failed", failed_stage=None, error_code=None)
    rev = db.add_revision(job, approved=True)
    run = db.add_run(job, rev, status="failed", error_stage=None, error_code=None)
    assert retry(api, auth, job, run).status_code == 409
    assert db.job(job["id"])["status"] == "failed"


# === task-035 V2 → task-036: 예능형 렌더 요청·재시도 허용, 렌더러 없는 형식은 409 ==========


def test_v2_variety_render_request_creates_run(api, auth, db):
    job = db.add_job(status="review", format="variety", preset_version="variety-1080-v1")
    rev = db.add_revision(job, approved=True)
    r = render(api, auth, job, rev)
    assert r.status_code == 202
    assert r.json()["render_run"]["preset_version"] == "variety-1080-v1"
    assert len(db.runs) == 1 and db.job(job["id"])["status"] == "rendering"
    assert "request" in db.rpc_calls


def test_v2_variety_retry_creates_new_run(api, auth, db):
    job = db.add_job(status="failed", failed_stage="render", error_code="render_failed")
    job.update(format="variety", preset_version="variety-1080-v1")
    rev = db.add_revision(job, approved=True)
    run = db.add_run(job, rev, status="failed", error_stage="render", error_code="render_failed")
    r = retry(api, auth, job, run)
    assert r.status_code == 202 and r.json()["render_run"]["attempt"] == 2
    assert len(db.runs) == 2 and db.job(job["id"])["status"] == "rendering"


def test_v2_format_without_renderer_is_409_without_run(api, auth, db):
    job = db.add_job(status="review", format="unknown")  # task-045: shopping은 렌더러 연결
    rev = db.add_revision(job, approved=True)
    r = render(api, auth, job, rev)
    assert r.status_code == 409
    assert r.json()["code"] == "CONFLICT" and r.json()["field"] == "format"
    assert db.runs == [] and "request" not in db.rpc_calls
    job.update(status="failed", failed_stage="render", error_code="render_failed")
    run = db.add_run(job, rev, status="failed", error_stage="render", error_code="render_failed")
    r = retry(api, auth, job, run)
    assert r.status_code == 409 and r.json()["field"] == "format"
    assert "retry" not in db.rpc_calls
