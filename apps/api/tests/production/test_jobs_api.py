"""task-022 제작 작업 API(A-09~A-13·A-17·A-18) 단위 테스트.

가짜 PostgREST(메모리)와 가짜 Storage를 respx로 붙인다. RPC(save/approve_production_revision)는
supabase/migrations/20261119000016_production_api.sql을 본뜬다(실제 SQL은 pgTAP이 검사).
완료 조건 5항목과 착수 결정 D1~D9를 각각 1건 이상 확인한다.
"""

import base64
import io
import json
import logging
import sys
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.logging_mask import setup_logging
from app.main import create_app
from tests.conftest import (
    JWKS_URL,
    OTHER_WORKSPACE_ID,
    SUPABASE_URL,
    USER_ID,
    WORKSPACE_ID,
    make_settings,
)
from tests.production.test_validation_variety import good as variety_good

REST = f"{SUPABASE_URL}/rest/v1"
STORAGE = f"{SUPABASE_URL}/storage/v1"
WS = str(WORKSPACE_ID)
OTHER_WS = str(OTHER_WORKSPACE_ID)
USER = str(USER_ID)
CAND = "00000000-0000-4000-8000-0000000000b1"
CAND_OTHER = "00000000-0000-4000-8000-0000000000b9"
WORKER = "00000000-0000-4000-8000-0000000000c1"
URL = "/v1/production-jobs"
MB = 1024 * 1024
_META = {"select", "order", "limit", "offset"}


def _b64(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


def fake_token(ttl: int) -> str:
    """Storage 서명 토큰 모양(header.payload.sig). 런타임 조립(리터럴 금지)."""
    now = int(time.time())
    sig = "s" + uuid.uuid4().hex + uuid.uuid4().hex
    return f"{_b64({'alg': 'HS256'})}.{_b64({'iat': now, 'exp': now + ttl})}.{sig}"


def good_spec() -> dict:
    return {
        "lang": "ko",
        "header": {"lines": ["제목 첫줄", "제목 둘째줄"]},
        "hook": {"text": "훅", "audio_asset_id": "a-1"},
        "duration": 10.0,
        "shots": [{"start": 0, "end": 10, "scale": 1.0, "y": 0}],
        "items": [{"start": 0, "end": 10, "kind": "white", "text": "훅"}],
    }


def bad_spec() -> dict:
    """스키마는 맞고 의미 오류(구도 공백)가 있는 편집안."""
    s = good_spec()
    s["shots"] = [{"start": 0, "end": 5, "scale": 1.0, "y": 0}]
    return s


def _params(request: httpx.Request) -> dict[str, str]:
    return {k: v[-1] for k, v in parse_qs(request.url.query.decode()).items()}


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
        elif raw == "not.is.null":
            if cur is None:
                return False
        else:
            raise AssertionError(f"지원하지 않는 필터 {key}={raw}")
    return True


def _select(rows: list[dict], params: dict[str, str]) -> list[dict]:
    out = [r for r in rows if _match(r, params)]
    for part in reversed((params.get("order") or "").split(",")):
        if part:
            col, _, direction = part.partition(".")
            out.sort(key=lambda r, c=col: str(r.get(c)), reverse=direction == "desc")
    offset = int(params.get("offset", 0))
    out = out[offset:]
    if "limit" in params:
        out = out[: int(params["limit"])]
    cols = params.get("select")
    if cols and cols != "*":
        out = [{c: r.get(c) for c in cols.split(",")} for r in out]
    return out


def _now() -> str:
    return datetime.now(UTC).isoformat()


def same_ts(a: str, b: str) -> bool:
    """timestamptz 비교(000030 L3): 문자열 표기와 무관하게 같은 시각인지."""
    return datetime.fromisoformat(a) == datetime.fromisoformat(b)


STALE_TS = "2000-01-01T00:00:00Z"


def cur_updated_at(api, auth, jid: str, lang: str = "ko") -> str:
    """웹처럼 A-12 GET으로 읽은 updated_at(task-059). 읽을 수 없으면 낡은 값."""
    r = api.get(f"{URL}/{jid}/revision", params={"lang": lang}, headers=auth)
    return r.json()["revision"]["updated_at"] if r.status_code == 200 else STALE_TS


def job_row(jid: str | None = None, ws: str = WS, status: str = "draft", **over: Any) -> dict:
    row = {
        "id": jid or str(uuid.uuid4()),
        "workspace_id": ws,
        "title": "작업",
        "format": "category",
        "status": status,
        "failed_stage": None,
        "error_code": None,
        "transcribe_state": None,
        "transcribe_error": None,
        "transcribe_updated_at": None,
        "candidate_id": None,
        "source_kind": "upload",
        "source_url": None,
        "rights_confirmed": False,
        "rights_confirmed_by": None,
        "rights_confirmed_at": None,
        "license_cc": None,
        "credit": None,
        "source_start_sec": 0,
        "segment_len_sec": 60,
        "lang": "ko",
        "preset_version": "category-1080-v1",
        "source_meta": None,
        "current_revision_id": None,
        "ai_draft_count": 0,
        "retry_count": 0,
        "claimed_by": None,
        "updated_at": "2026-11-01T00:00:00+00:00",
        "requested_by": USER,
        "created_at": _now(),
        "completed_at": None,
        "idempotency_key": f"k-{uuid.uuid4().hex[:8]}",
        "kind": "general",
        "vertical": None,
        "brief": None,
        "affiliates": [],
        "comment_keyword": None,
        "current_ja_revision_id": None,
    }
    row.update(over)
    return row


@dataclass
class FakeDB:
    jobs: list[dict] = field(default_factory=list)
    assets: list[dict] = field(default_factory=list)
    revisions: list[dict] = field(default_factory=list)
    runs: list[dict] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)
    workers: list[dict] = field(default_factory=list)
    heartbeats: list[dict] = field(default_factory=list)
    objects: dict[str, int] = field(default_factory=dict)  # Storage 경로 → 크기
    issued_tokens: list[str] = field(default_factory=list)
    hide_key_lookups: int = 0  # 멱등 키 조회를 이 횟수만큼 빈 결과로(동시 요청 흉내)
    touch_revision_on_read: bool = False
    hide_ready_source: bool = (
        False  # 원본 ready 확인 조회를 놓치는 경합 흉내  # 재검증 후 다른 저장이 끼어든 상황 흉내
    )
    rpc_calls: list[str] = field(default_factory=list)
    asset_insert_error: str | None = None  # task-044: 자산 insert를 이 SQLSTATE로 거부(트리거 경합)
    fail_tables: set[str] = field(default_factory=set)  # 이 테이블 요청은 500(저장소 오류)
    # "METHOD table" → SQLSTATE: 트리거(000023)가 쓰기를 거부한 경합 흉내
    write_errors: dict[str, str] = field(default_factory=dict)

    def table(self, name: str) -> list[dict]:
        return {
            "production_jobs": self.jobs,
            "production_assets": self.assets,
            "edit_revisions": self.revisions,
            "render_runs": self.runs,
            "candidates": self.candidates,
            "workers": self.workers,
            "worker_heartbeats": self.heartbeats,
        }[name]

    # --- 테스트 픽스처 헬퍼 ---
    def add_job(self, **over: Any) -> dict:
        row = job_row(**over)
        self.jobs.append(row)
        return row

    def add_revision(self, job: dict, rev_no: int = 1, approved: bool = False, **over: Any) -> dict:
        rev = {
            "id": str(uuid.uuid4()),
            "workspace_id": job["workspace_id"],
            "job_id": job["id"],
            "lang": "ko",
            "rev_no": rev_no,
            "schema_version": 1,
            "spec": good_spec(),
            "origin": "user",
            "validation": {"errors": [], "warnings": []},
            "approved_at": _now() if approved else None,
            "approved_by": USER if approved else None,
            "created_by": USER,
            "created_at": _now(),
            "updated_at": "2026-11-02T00:00:00.123456+00:00",
        }
        rev.update(over)
        self.revisions.append(rev)
        job["current_revision_id"] = rev["id"]
        return rev

    def add_asset(self, job: dict, kind: str, status: str = "ready", **over: Any) -> dict:
        aid = str(uuid.uuid4())
        row = {
            "id": aid,
            "workspace_id": job["workspace_id"],
            "job_id": job["id"],
            "kind": kind,
            "storage_path": f"{job['workspace_id']}/{job['id']}/{aid}.mp4",
            "mime": "video/mp4",
            "size_bytes": 1000,
            "duration_sec": None,
            "status": status,
            "render_run_id": None,
            "parent_asset_id": None,
            "rights": None,
            "created_by": USER,
            "created_at": _now(),
        }
        row.update(over)
        self.assets.append(row)
        return row

    # --- RPC(000016 본뜸) ---
    def _locked_job(self, body: dict) -> dict | None:
        return next(
            (
                j
                for j in self.jobs
                if j["id"] == body["p_job"] and j["workspace_id"] == body["p_workspace"]
            ),
            None,
        )

    def save_revision(self, body: dict) -> httpx.Response:
        self.rpc_calls.append("save")
        j = self._locked_job(body)
        if j is None:
            return _rpc_error("NR009")
        if (
            not (
                j["status"] in ("review", "inspect")
                or (j["status"] == "failed" and j["failed_stage"] in ("audio", "render"))
            )
            or not j["current_revision_id"]
        ):
            return _rpc_error("NR010")
        rev = next(r for r in self.revisions if r["id"] == j["current_revision_id"])
        if rev["rev_no"] != body["p_base_rev_no"] or not same_ts(
            rev["updated_at"], body["p_base_updated_at"]
        ):
            return _rpc_error("NR011")
        if rev["approved_at"] is None:
            rev.update(spec=body["p_spec"], validation=body["p_validation"], updated_at=_now())
        else:
            rev = {
                **rev,
                "id": str(uuid.uuid4()),
                "rev_no": max(r["rev_no"] for r in self.revisions if r["job_id"] == j["id"]) + 1,
                "spec": body["p_spec"],
                "origin": "user",
                "validation": body["p_validation"],
                "approved_at": None,
                "approved_by": None,
                "created_by": body["p_user"],
                "updated_at": _now(),
            }
            self.revisions.append(rev)
            j["current_revision_id"] = rev["id"]
        if j["status"] in ("inspect", "failed"):
            j.update(status="review", failed_stage=None, error_code=None, updated_at=_now())
        out = {
            k: rev[k]
            for k in ("id", "rev_no", "spec", "origin", "validation", "approved_at", "updated_at")
        }
        return httpx.Response(200, json=out)

    def approve_revision(self, body: dict) -> httpx.Response:
        self.rpc_calls.append("approve")
        j = self._locked_job(body)
        if j is None:
            return _rpc_error("NR009")
        if j["status"] != "review" or not j["current_revision_id"]:
            return _rpc_error("NR010")
        rev = next(r for r in self.revisions if r["id"] == j["current_revision_id"])
        if rev["rev_no"] != body["p_rev_no"] or rev["updated_at"] != body["p_updated_at"]:
            return _rpc_error("NR011")
        if rev["approved_at"] is not None:
            return _rpc_error("NR010")
        rev.update(approved_at=_now(), approved_by=body["p_user"], validation=body["p_validation"])
        out = {k: rev[k] for k in ("id", "rev_no", "approved_at", "approved_by")}
        return httpx.Response(200, json=out)

    # --- Storage ---
    def _path(self, request: httpx.Request, prefix: str) -> str:
        return request.url.path.split(f"/storage/v1/{prefix}/production/", 1)[1]

    def sign_upload(self, request: httpx.Request) -> httpx.Response:
        path = self._path(request, "object/upload/sign")
        token = fake_token(7200)
        self.issued_tokens.append(token)
        return httpx.Response(
            200,
            json={"url": f"/object/upload/sign/production/{path}?token={token}", "token": token},
        )

    def sign_download(self, request: httpx.Request) -> httpx.Response:
        path = self._path(request, "object/sign")
        ttl = json.loads(request.content)["expiresIn"]
        token = fake_token(ttl)
        self.issued_tokens.append(token)
        return httpx.Response(
            200, json={"signedURL": f"/object/sign/production/{path}?token={token}"}
        )

    def info(self, request: httpx.Request) -> httpx.Response:
        path = self._path(request, "object/info")
        if path not in self.objects:
            return httpx.Response(400, json={"statusCode": "404", "error": "not_found"})
        return httpx.Response(200, json={"size": self.objects[path], "content_type": "video/mp4"})

    def delete(self, request: httpx.Request) -> httpx.Response:
        path = self._path(request, "object")
        if self.objects.pop(path, None) is None:
            return httpx.Response(400, json={"statusCode": "404", "error": "not_found"})
        return httpx.Response(200, json={"message": "ok"})


def _rpc_error(code: str) -> httpx.Response:
    return httpx.Response(400, json={"code": code, "message": "x"})


def install(router: respx.MockRouter, db: FakeDB) -> None:
    def rest(request: httpx.Request, name: str) -> httpx.Response:
        rows = db.table(name)
        p = _params(request)
        if name in db.fail_tables:
            return httpx.Response(500, json={"message": "x"})
        if f"{request.method} {name}" in db.write_errors:
            code = db.write_errors[f"{request.method} {name}"]
            return httpx.Response(400, json={"code": code, "message": "x"})
        if request.method == "GET":
            if name == "production_jobs" and "idempotency_key" in p and db.hide_key_lookups > 0:
                db.hide_key_lookups -= 1
                return httpx.Response(200, json=[])
            out = _select(rows, p)
            if name == "production_assets" and db.hide_ready_source and "kind" in p:
                out = [r for r in out if r.get("status") != "ready"]
            if name == "edit_revisions" and db.touch_revision_on_read:
                for r in rows:
                    if _match(r, p):
                        r["updated_at"] = _now()
            return httpx.Response(200, json=out)
        if request.method == "DELETE":
            hit = [r for r in rows if _match(r, p)]
            for r in hit:
                rows.remove(r)
            return httpx.Response(200, json=_select(hit, {"select": p.get("select", "*")}))
        body = json.loads(request.content)
        if request.method == "PATCH":
            hit = [r for r in rows if _match(r, p)]
            if name == "production_assets" and body.get("status") == "ready":
                for r in hit:
                    job_kind = next(
                        (j.get("kind") for j in db.jobs if j["id"] == r["job_id"]), "general"
                    )
                    # 000023 트리거: 일반 작업만 ready 원본 1건
                    if (
                        job_kind != "shopping"
                        and r["kind"] == "source_upload"
                        and any(
                            o is not r
                            and o["job_id"] == r["job_id"]
                            and o["kind"] == "source_upload"
                            and o["status"] == "ready"
                            for o in rows
                        )
                    ):
                        return httpx.Response(
                            409,
                            json={
                                "code": "23505",
                                "message": "duplicate key value violates unique constraint "
                                '"production_assets_one_ready_source_uidx"',
                            },
                        )
            for r in hit:
                r.update(body)
            return httpx.Response(200, json=_select(hit, {"select": p.get("select", "*")}))
        # POST insert
        if name == "production_jobs":
            if any(
                j["workspace_id"] == body["workspace_id"]
                and j["idempotency_key"] == body["idempotency_key"]
                for j in db.jobs
            ):
                return httpx.Response(
                    409,
                    json={
                        "code": "23505",
                        "message": "duplicate key value violates unique constraint "
                        '"production_jobs_workspace_id_idempotency_key_key"',
                    },
                )
            new = job_row()
            new.update(body)
            db.jobs.append(new)
        else:
            assert name == "production_assets"
            if db.asset_insert_error:
                return httpx.Response(409, json={"code": db.asset_insert_error, "message": "x"})
            new = {
                "duration_sec": None,
                "render_run_id": None,
                "parent_asset_id": None,
                "rights": None,
                "created_at": _now(),
                **body,
            }
            db.assets.append(new)
        return httpx.Response(201, json=_select([new], {"select": p.get("select", "*")}))

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
    router.post(f"{REST}/rpc/save_production_revision").mock(
        side_effect=lambda r: db.save_revision(json.loads(r.content))
    )
    # task-023 E3: A-09 GET의 오프라인 지연 평가(만료 대상 없음으로 본다)
    router.post(f"{REST}/rpc/expire_production_offline").mock(
        return_value=httpx.Response(200, json={"expired": 0, "deleted_paths": []})
    )
    router.post(f"{REST}/rpc/approve_production_revision").mock(
        side_effect=lambda r: db.approve_revision(json.loads(r.content))
    )
    router.post(url__startswith=f"{STORAGE}/object/upload/sign/production/").mock(
        side_effect=db.sign_upload
    )
    router.post(url__startswith=f"{STORAGE}/object/sign/production/").mock(
        side_effect=db.sign_download
    )
    router.get(url__startswith=f"{STORAGE}/object/info/production/").mock(side_effect=db.info)
    router.delete(url__startswith=f"{STORAGE}/object/production/").mock(side_effect=db.delete)


@pytest.fixture
def db() -> FakeDB:
    return FakeDB(
        candidates=[
            {"id": CAND, "workspace_id": WS},
            {"id": CAND_OTHER, "workspace_id": OTHER_WS},
        ],
        workers=[{"id": WORKER, "workspace_id": WS, "revoked_at": None}],
        heartbeats=[{"worker_id": WORKER, "workspace_id": WS, "last_seen_at": _now()}],
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


def create_body(**over: Any) -> dict:
    body = {
        "title": "새 작업",
        "source_kind": "upload",
        "rights_confirmed": False,
        "source_start_sec": 12.5,
        "segment_len_sec": 60,
    }
    body.update(over)
    return body


def post_job(api: TestClient, auth: dict, key: str = "key-1", **over: Any) -> httpx.Response:
    return api.post(URL, json=create_body(**over), headers={**auth, "Idempotency-Key": key})


# === A-09 생성·멱등(D1) ==========================================================


def test_create_job_201_draft_with_server_values(api, auth, db):
    r = post_job(api, auth, candidate_id=CAND)
    assert r.status_code == 201
    job = r.json()["job"]
    assert job["status"] == "draft"
    assert job["format"] == "category"
    assert job["preset_version"] == "category-1080-v1"
    assert job["candidate_id"] == CAND
    assert job["requested_by"] == USER
    assert "claimed_by" not in job and "idempotency_key" not in job
    assert db.jobs[0]["idempotency_key"] == "key-1"


def test_d1_same_key_returns_200_existing_even_if_body_differs(api, auth, db):
    first = post_job(api, auth, key="same").json()["job"]
    again = post_job(api, auth, key="same", title="다른 제목", segment_len_sec=30)
    assert again.status_code == 200
    assert again.json()["job"]["id"] == first["id"]
    assert again.json()["job"]["title"] == "새 작업"
    assert len(db.jobs) == 1


def test_d1_unique_violation_refetches_existing(api, auth, db):
    existing = db.add_job(idempotency_key="race")
    db.hide_key_lookups = 1  # 첫 조회는 못 봄 → insert 23505 → 재조회
    r = post_job(api, auth, key="race")
    assert r.status_code == 200
    assert r.json()["job"]["id"] == existing["id"]
    assert len(db.jobs) == 1


def test_create_requires_idempotency_key(api, auth):
    r = api.post(URL, json=create_body(), headers=auth)
    assert r.status_code == 400
    assert r.json()["field"] == "Idempotency-Key"


def test_same_key_other_workspace_is_independent(api, auth, db):
    db.add_job(ws=OTHER_WS, idempotency_key="shared")
    r = post_job(api, auth, key="shared")
    assert r.status_code == 201
    assert r.json()["job"]["workspace_id"] == WS


def test_shopping_format_needs_shopping_kind(api, auth, db):
    # task-044: format=shopping은 kind=shopping과 짝(일반 kind면 400)
    r = post_job(api, auth, format="shopping")
    assert r.status_code == 400
    assert r.json() == {
        "code": "VALIDATION",
        "message": "유형과 형식이 맞지 않습니다.",
        "field": "format",
    }
    assert db.jobs == []


@pytest.mark.parametrize(
    "over",
    [{"segment_len_sec": 0}, {"segment_len_sec": 181}, {"source_start_sec": -1}, {"title": " "}],
)
def test_create_range_validation(api, auth, over):
    assert post_job(api, auth, **over).status_code == 400


def test_candidate_from_other_workspace_404(api, auth, db):
    r = post_job(api, auth, candidate_id=CAND_OTHER)
    assert r.status_code == 404
    assert db.jobs == []


def test_d6_url_source_rejected(api, auth, db):
    # task-031: URL 원본은 YouTube만(나머지 검사는 test_url_guard.py)
    r = post_job(
        api, auth, source_kind="url", source_url="https://example.com/v", rights_confirmed=True
    )
    assert r.status_code == 400
    assert r.json()["field"] == "source_url"
    assert db.jobs == []


# === 권리 확인(D7) ============================================================


def test_d7_create_with_rights_sets_by_and_at(api, auth):
    job = post_job(api, auth, rights_confirmed=True).json()["job"]
    assert job["rights_confirmed_by"] == USER
    assert job["rights_confirmed_at"] is not None


@pytest.mark.parametrize("extra", ["rights_confirmed_by", "rights_confirmed_at"])
def test_d7_client_cannot_send_rights_by_at(api, auth, db, extra):
    r = post_job(api, auth, **{extra: USER if extra.endswith("by") else _now()})
    assert r.status_code == 400
    assert db.jobs == []
    job = db.add_job()
    r = api.patch(f"{URL}/{job['id']}", json={extra: USER}, headers=auth)
    assert r.status_code == 400


def test_d7_patch_rights_transitions(api, auth, db):
    job = db.add_job()
    r = api.patch(f"{URL}/{job['id']}", json={"rights_confirmed": True}, headers=auth)
    assert r.status_code == 200
    first_at = r.json()["job"]["rights_confirmed_at"]
    assert r.json()["job"]["rights_confirmed_by"] == USER and first_at
    # true 재전송은 by·at 유지
    r = api.patch(f"{URL}/{job['id']}", json={"rights_confirmed": True}, headers=auth)
    assert r.json()["job"]["rights_confirmed_at"] == first_at
    # false면 둘 다 null
    r = api.patch(f"{URL}/{job['id']}", json={"rights_confirmed": False}, headers=auth)
    assert r.json()["job"]["rights_confirmed_by"] is None
    assert r.json()["job"]["rights_confirmed_at"] is None


# === A-09 PATCH·GET ===========================================================


def test_patch_only_sent_fields(api, auth, db):
    job = db.add_job(credit="원작자", license_cc=True)
    r = api.patch(f"{URL}/{job['id']}", json={"segment_len_sec": 30}, headers=auth)
    assert r.status_code == 200
    out = r.json()["job"]
    assert out["segment_len_sec"] == 30
    assert out["credit"] == "원작자" and out["license_cc"] is True


def test_patch_format_change_rejected(api, auth, db):
    job = db.add_job()
    assert (
        api.patch(f"{URL}/{job['id']}", json={"format": "variety"}, headers=auth).status_code == 400
    )


def test_patch_409_when_not_draft_or_failed_prepare(api, auth, db):
    job = db.add_job(status="review")
    r = api.patch(f"{URL}/{job['id']}", json={"segment_len_sec": 30}, headers=auth)
    assert r.status_code == 409
    assert r.json()["code"] == "CONFLICT"
    assert "review" in r.json()["message"]
    failed_render = db.add_job(status="failed", failed_stage="render")
    r = api.patch(f"{URL}/{failed_render['id']}", json={"segment_len_sec": 30}, headers=auth)
    assert r.status_code == 409
    failed_prepare = db.add_job(status="failed", failed_stage="prepare")
    r = api.patch(f"{URL}/{failed_prepare['id']}", json={"segment_len_sec": 30}, headers=auth)
    assert r.status_code == 200


def test_other_workspace_job_is_404_everywhere(api, auth, db):
    job = db.add_job(ws=OTHER_WS, status="review")
    rev = db.add_revision(job)
    asset = db.add_asset(job, "source")
    jid = job["id"]
    calls = [
        api.get(f"{URL}/{jid}", headers=auth),
        api.patch(f"{URL}/{jid}", json={"segment_len_sec": 30}, headers=auth),
        api.post(
            f"{URL}/{jid}/uploads",
            json={"kind": "hook_audio", "size_bytes": 10, "mime": "audio/wav"},
            headers=auth,
        ),
        api.post(f"{URL}/{jid}/uploads/{asset['id']}/complete", headers=auth),
        api.post(f"{URL}/{jid}/prepare", headers=auth),
        api.get(f"{URL}/{jid}/revision", headers=auth),
        api.put(
            f"{URL}/{jid}/revision",
            json={"spec": good_spec(), "base_rev_no": 1, "base_updated_at": STALE_TS},
            headers=auth,
        ),
        api.post(f"{URL}/{jid}/revision/approve", json={"rev_no": 1}, headers=auth),
        api.post(f"{URL}/{jid}/review/approve", headers=auth),
        api.get(f"{URL}/{jid}/assets/{asset['id']}/download-url", headers=auth),
    ]
    assert [c.status_code for c in calls] == [404] * len(calls)
    assert rev["spec"] == good_spec()
    assert db.issued_tokens == []


def test_list_jobs_scoped_and_filtered(api, auth, db):
    db.add_job(status="draft", title="a")
    db.add_job(status="review", title="b")
    db.add_job(ws=OTHER_WS, title="other")
    r = api.get(URL, headers=auth)
    assert {i["title"] for i in r.json()["items"]} == {"a", "b"}
    r = api.get(URL, params={"status": "review"}, headers=auth)
    assert [i["title"] for i in r.json()["items"]] == ["b"]
    assert api.get(URL, params={"size": 61}, headers=auth).status_code == 400


def test_get_detail_shape(api, auth, db):
    job = db.add_job(status="review", claimed_by=WORKER)
    db.add_revision(job)
    db.add_asset(job, "source", duration_sec=10)
    r = api.get(f"{URL}/{job['id']}", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert "claimed_by" not in body["job"]
    assert body["assets"][0]["kind"] == "source"
    assert "storage_path" not in body["assets"][0]
    assert body["current_revision"]["ko"]["rev_no"] == 1
    assert body["current_revision"]["ja"] is None
    assert body["latest_run"] is None
    assert body["worker_online"] is True


# === A-10 업로드(D4·D5·D9) =====================================================


def upload(
    api, auth, jid: str, kind: str = "source_upload", size: int = 5 * MB, mime: str = "video/mp4"
):
    return api.post(
        f"{URL}/{jid}/uploads", json={"kind": kind, "size_bytes": size, "mime": mime}, headers=auth
    )


def test_d4_upload_sign_returns_pending_asset_and_token_expiry(api, auth, db):
    job = db.add_job()
    before = datetime.now(UTC)
    r = upload(api, auth, job["id"])
    assert r.status_code == 201
    body = r.json()
    assert body["asset"]["status"] == "pending"
    assert body["upload_url"].startswith(f"{STORAGE}/object/upload/sign/production/")
    assert r.headers["cache-control"] == "no-store"
    expires = datetime.fromisoformat(body["expires_at"])
    # Supabase 업로드 서명은 만료 지정 불가 → 토큰 exp(기본 2시간)를 그대로 알린다
    assert timedelta(seconds=7190) <= expires - before <= timedelta(seconds=7210)
    row = db.assets[0]
    assert row["storage_path"] == f"{WS}/{job['id']}/{row['id']}.mp4"
    assert row["size_bytes"] == 5 * MB and row["created_by"] == USER


def test_upload_rejects_client_path_and_bad_mime(api, auth, db):
    job = db.add_job()
    r = api.post(
        f"{URL}/{job['id']}/uploads",
        json={"kind": "source_upload", "size_bytes": 10, "mime": "video/mp4", "path": "../x.mp4"},
        headers=auth,
    )
    assert r.status_code == 400
    assert upload(api, auth, job["id"], mime="application/x-sh").status_code == 400
    assert upload(api, auth, job["id"], mime="audio/wav").status_code == 400  # 원본은 영상만
    assert db.assets == []


def test_upload_size_limit_500mb(api, auth, db):
    job = db.add_job()
    assert upload(api, auth, job["id"], size=524_288_001).status_code == 400
    assert upload(api, auth, job["id"], size=0).status_code == 400
    assert upload(api, auth, job["id"], size=524_288_000).status_code == 201


def test_d5_source_upload_state_rules(api, auth, db):
    review = db.add_job(status="review")
    assert upload(api, auth, review["id"]).status_code == 409
    failed_prepare = db.add_job(status="failed", failed_stage="prepare")
    assert upload(api, auth, failed_prepare["id"]).status_code == 201


def test_d5_new_source_upload_replaces_pending_and_blocks_after_ready(api, auth, db):
    job = db.add_job()
    old = db.add_asset(job, "source_upload", status="pending")
    db.objects[old["storage_path"]] = 10
    assert upload(api, auth, job["id"]).status_code == 201
    assert old not in db.assets and old["storage_path"] not in db.objects
    assert len([a for a in db.assets if a["kind"] == "source_upload"]) == 1
    db.assets[0]["status"] = "ready"
    r = upload(api, auth, job["id"])
    assert r.status_code == 409


def test_d5_hook_audio_state_and_format_rules(api, auth, db):
    draft = db.add_job()
    assert upload(api, auth, draft["id"], kind="hook_audio", mime="audio/wav").status_code == 409
    review = db.add_job(status="review")
    r = upload(api, auth, review["id"], kind="hook_audio", mime="audio/mpeg")
    assert r.status_code == 201
    assert db.assets[-1]["storage_path"].endswith(".mp3")
    failed_render = db.add_job(status="failed", failed_stage="render")
    assert (
        upload(api, auth, failed_render["id"], kind="hook_audio", mime="audio/wav").status_code
        == 201
    )
    failed_audio = db.add_job(status="failed", failed_stage="audio")
    assert (
        upload(api, auth, failed_audio["id"], kind="hook_audio", mime="audio/wav").status_code
        == 201  # task-023 E10: audio_missing 복구
    )
    variety = db.add_job(status="review", format="variety")
    assert upload(api, auth, variety["id"], kind="hook_audio", mime="audio/wav").status_code == 400


def test_d5_complete_checks_real_size(api, auth, db):
    job = db.add_job()
    asset = upload(api, auth, job["id"], size=1234).json()["asset"]
    path = db.assets[0]["storage_path"]
    done = f"{URL}/{job['id']}/uploads/{asset['id']}/complete"
    assert api.post(done, headers=auth).status_code == 409  # 객체 없음
    db.objects[path] = 1234
    r = api.post(done, headers=auth)
    assert r.status_code == 200
    assert r.json()["asset"]["status"] == "ready"
    # 이미 ready면 200(멱등)
    assert api.post(done, headers=auth).status_code == 200


def test_d9_asset_lookup_requires_matching_job(api, auth, db):
    job_a = db.add_job()
    job_b = db.add_job(status="inspect")
    asset = db.add_asset(job_a, "source_upload", status="pending")
    out = db.add_asset(job_b, "output_mp4")
    assert (
        api.post(f"{URL}/{job_b['id']}/uploads/{asset['id']}/complete", headers=auth).status_code
        == 404
    )
    assert (
        api.get(f"{URL}/{job_a['id']}/assets/{out['id']}/download-url", headers=auth).status_code
        == 404
    )
    assert db.issued_tokens == []


def test_complete_rejects_worker_asset_kind(api, auth, db):
    job = db.add_job()
    asset = db.add_asset(job, "analysis", status="pending")
    assert (
        api.post(f"{URL}/{job['id']}/uploads/{asset['id']}/complete", headers=auth).status_code
        == 409
    )


# === A-11 prepare(D8) =========================================================


def test_d8_prepare_from_draft(api, auth, db):
    job = db.add_job(error_code=None)
    db.add_asset(job, "source_upload")
    r = api.post(f"{URL}/{job['id']}/prepare", headers=auth)
    assert r.status_code == 202
    out = r.json()["job"]
    assert out["status"] == "preparing" and out["retry_count"] == 0
    assert datetime.fromisoformat(out["updated_at"]) > datetime.now(UTC) - timedelta(minutes=1)


def test_d8_prepare_retry_counts_and_clears_failure(api, auth, db):
    job = db.add_job(
        status="failed",
        failed_stage="prepare",
        error_code="download_failed",
        retry_count=1,
        claimed_by=WORKER,
    )
    db.add_asset(job, "source_upload")
    r = api.post(f"{URL}/{job['id']}/prepare", headers=auth)
    assert r.status_code == 202
    assert r.json()["job"]["retry_count"] == 2
    row = db.jobs[0]
    assert row["failed_stage"] is None and row["error_code"] is None and row["claimed_by"] is None


def test_d8_prepare_409_and_400(api, auth, db):
    capped = db.add_job(status="failed", failed_stage="prepare", retry_count=3)
    db.add_asset(capped, "source_upload")
    assert api.post(f"{URL}/{capped['id']}/prepare", headers=auth).status_code == 409
    preparing = db.add_job(status="preparing")
    assert api.post(f"{URL}/{preparing['id']}/prepare", headers=auth).status_code == 409
    failed_render = db.add_job(status="failed", failed_stage="render")
    assert api.post(f"{URL}/{failed_render['id']}/prepare", headers=auth).status_code == 409
    no_source = db.add_job()
    db.add_asset(no_source, "source_upload", status="pending")
    r = api.post(f"{URL}/{no_source['id']}/prepare", headers=auth)
    assert r.status_code == 400 and no_source["status"] == "draft"


# === A-12 리비전(D2·D3) =======================================================


def put_rev(api, auth, jid: str, spec: dict, base: int = 1, base_updated_at: str | None = None):
    at = base_updated_at or cur_updated_at(api, auth, jid)
    body = {"spec": spec, "base_rev_no": base, "base_updated_at": at}
    return api.put(f"{URL}/{jid}/revision", json=body, headers=auth)


def test_get_revision_current_and_by_rev_no(api, auth, db):
    job = db.add_job(status="review")
    db.add_revision(job, rev_no=1, approved=True)
    db.add_revision(job, rev_no=2)
    r = api.get(f"{URL}/{job['id']}/revision", headers=auth)
    assert r.status_code == 200 and r.json()["revision"]["rev_no"] == 2
    r = api.get(f"{URL}/{job['id']}/revision", params={"rev_no": 1}, headers=auth)
    assert r.json()["revision"]["approved_at"] is not None
    assert (
        api.get(f"{URL}/{job['id']}/revision", params={"rev_no": 9}, headers=auth).status_code
        == 404
    )


def test_d2_put_saves_with_errors_in_place_when_unapproved(api, auth, db):
    job = db.add_job(status="review")
    rev = db.add_revision(job)
    r = put_rev(api, auth, job["id"], bad_spec())
    assert r.status_code == 200
    out = r.json()["revision"]
    assert out["id"] == rev["id"] and out["rev_no"] == 1
    assert out["validation"]["errors"]  # 오류가 있어도 저장
    assert rev["spec"] == bad_spec()


def test_d2_put_on_approved_creates_new_rev_and_inspect_returns_to_review(api, auth, db):
    job = db.add_job(status="inspect")
    old = db.add_revision(job, approved=True)
    r = put_rev(api, auth, job["id"], good_spec())
    assert r.status_code == 200
    out = r.json()["revision"]
    assert out["rev_no"] == 2 and out["approved_at"] is None
    assert job["current_revision_id"] == out["id"] != old["id"]
    assert job["status"] == "review"
    assert old["spec"] == good_spec() and old["approved_at"] is not None


def test_d2_put_base_rev_no_mismatch_409(api, auth, db):
    job = db.add_job(status="review")
    db.add_revision(job, rev_no=3)
    r = put_rev(api, auth, job["id"], good_spec(), base=2)
    assert r.status_code == 409 and r.json()["field"] == "base_rev_no"


# --- task-059 L3·L4·L5: base_updated_at 낙관적 잠금(필수 누락은 이 앱 규약대로 400 VALIDATION) ---


def test_l4_put_without_base_updated_at_400(api, auth, db):
    job = db.add_job(status="review")
    db.add_revision(job)
    r = api.put(
        f"{URL}/{job['id']}/revision", json={"spec": good_spec(), "base_rev_no": 1}, headers=auth
    )
    assert r.status_code == 400 and r.json()["field"] == "base_updated_at"
    assert "save" not in db.rpc_calls


def test_l4_put_naive_base_updated_at_400(api, auth, db):
    job = db.add_job(status="review")
    db.add_revision(job)
    r = put_rev(api, auth, job["id"], good_spec(), base_updated_at="2026-11-02T00:00:00.123456")
    assert r.status_code == 400 and r.json()["field"] == "base_updated_at"
    assert "save" not in db.rpc_calls


def test_l3_microsecond_roundtrip_get_to_put(api, auth, db):
    job = db.add_job(status="review")
    db.add_revision(job)  # updated_at 2026-11-02T00:00:00.123456+00:00
    at = api.get(f"{URL}/{job['id']}/revision", headers=auth).json()["revision"]["updated_at"]
    assert ".123456" in at
    stale = put_rev(api, auth, job["id"], good_spec(), base_updated_at=at.replace("456", "457"))
    assert stale.status_code == 409
    r = put_rev(api, auth, job["id"], good_spec(), base_updated_at=at)
    assert r.status_code == 200, r.text


def test_l5_consecutive_saves_then_stale_base_409(api, auth, db):
    job = db.add_job(status="review")
    rev = db.add_revision(job)
    first = cur_updated_at(api, auth, job["id"])
    r1 = put_rev(api, auth, job["id"], bad_spec(), base_updated_at=first)
    assert r1.status_code == 200
    r2 = put_rev(
        api, auth, job["id"], good_spec(), base_updated_at=r1.json()["revision"]["updated_at"]
    )
    assert r2.status_code == 200, r2.text
    # 앞선 화면(첫 GET 값)으로 다시 저장하면 409, 두 번째 편집 유지
    r3 = put_rev(api, auth, job["id"], bad_spec(), base_updated_at=first)
    assert r3.status_code == 409 and rev["spec"] == good_spec()


def test_l3_approved_revision_stale_base_409(api, auth, db):
    job = db.add_job(status="inspect")
    db.add_revision(job, approved=True)
    r = put_rev(api, auth, job["id"], good_spec(), base_updated_at=STALE_TS)
    assert r.status_code == 409 and job["status"] == "inspect"


def test_d3_put_allowed_states(api, auth, db):
    for status, stage in [("failed", "render"), ("failed", "audio")]:
        job = db.add_job(status=status, failed_stage=stage, error_code="hook_too_long")
        db.add_revision(job, approved=True)
        r = put_rev(api, auth, job["id"], good_spec())
        assert r.status_code == 200
        assert job["status"] == "review" and job["failed_stage"] is None
    for status, stage in [
        ("draft", None),
        ("preparing", None),
        ("rendering", None),
        ("done", None),
        ("failed", "prepare"),
    ]:
        job = db.add_job(status=status, failed_stage=stage)
        db.add_revision(job)
        assert put_rev(api, auth, job["id"], good_spec()).status_code == 409
    no_rev = db.add_job(status="review")
    assert put_rev(api, auth, no_rev["id"], good_spec()).status_code == 409


def test_put_path_field_rejected_and_not_saved(api, auth, db):
    job = db.add_job(status="review")
    rev = db.add_revision(job)
    spec = good_spec()
    spec["hook"]["audio_asset_id"] = "../../etc/passwd"
    r = put_rev(api, auth, job["id"], spec)
    assert r.status_code == 400
    assert [e["code"] for e in r.json()["errors"]] == ["path.forbidden"]
    assert rev["spec"] == good_spec()
    assert "save" not in db.rpc_calls


def test_put_schema_error_400_without_semantic_checks(api, auth, db):
    job = db.add_job(status="review")
    db.add_revision(job)
    spec = bad_spec()
    spec["unknown"] = 1
    r = put_rev(api, auth, job["id"], spec)
    assert r.status_code == 400
    assert all(e["code"].startswith("schema.") for e in r.json()["errors"])


def test_put_compares_job_values(api, auth, db):
    job = db.add_job(status="review", source_start_sec=12.5)
    db.add_revision(job)
    db.add_asset(job, "source", duration_sec=8)  # source 길이 → duration 상한 8.05
    spec = good_spec()
    spec["source_start_sec"] = 3
    spec["preset_version"] = "category-1080-v0"
    r = put_rev(api, auth, job["id"], spec)
    assert r.status_code == 200
    codes = {e["code"] for e in r.json()["revision"]["validation"]["errors"]}
    assert {"source_start_sec.mismatch", "preset_version.mismatch", "duration.range"} <= codes


# === A-13 승인(D2) ============================================================


def approve(api, auth, jid: str, rev_no: int = 1):
    return api.post(f"{URL}/{jid}/revision/approve", json={"rev_no": rev_no}, headers=auth)


def test_approve_success(api, auth, db):
    job = db.add_job(status="review")
    rev = db.add_revision(job)
    r = approve(api, auth, job["id"])
    assert r.status_code == 200
    assert r.json()["revision"]["approved_by"] == USER
    assert rev["approved_at"] is not None


def test_approve_spec_with_errors_400_server_revalidates(api, auth, db):
    job = db.add_job(status="review")
    # 저장된 validation은 비어 있어도 서버가 다시 검사한다
    rev = db.add_revision(job, spec=bad_spec(), validation={"errors": [], "warnings": []})
    r = approve(api, auth, job["id"])
    assert r.status_code == 400
    body = r.json()
    assert body["code"] == "VALIDATION"
    assert any(e["code"].startswith("shots.") for e in body["errors"])
    assert rev["approved_at"] is None
    assert "approve" not in db.rpc_calls


def test_approve_409_cases(api, auth, db):
    inspect = db.add_job(status="inspect")
    db.add_revision(inspect, approved=True)
    assert approve(api, auth, inspect["id"]).status_code == 409
    review = db.add_job(status="review")
    db.add_revision(review, rev_no=2)
    assert approve(api, auth, review["id"], rev_no=1).status_code == 409
    approved = db.add_job(status="review")
    db.add_revision(approved, approved=True)
    assert approve(api, auth, approved["id"]).status_code == 409


def test_d2_approve_409_when_revision_changed_after_revalidation(api, auth, db):
    job = db.add_job(status="review")
    rev = db.add_revision(job)
    db.touch_revision_on_read = True
    r = approve(api, auth, job["id"])
    assert r.status_code == 409 and r.json()["field"] == "rev_no"
    assert rev["approved_at"] is None


# === A-17 검수 승인(D9) =======================================================


def inspect_job(db: FakeDB, mp4_status: str = "ready") -> dict:
    job = db.add_job(status="inspect")
    rev = db.add_revision(job, approved=True)
    mp4 = db.add_asset(job, "output_mp4", status=mp4_status)
    db.runs.append(
        {
            "id": str(uuid.uuid4()),
            "workspace_id": WS,
            "job_id": job["id"],
            "revision_id": rev["id"],
            "lang": "ko",
            "status": "done",
            "mp4_asset_id": mp4["id"],
            "created_at": _now(),
        }
    )
    return job


def test_review_approve_done(api, auth, db):
    job = inspect_job(db)
    r = api.post(f"{URL}/{job['id']}/review/approve", headers=auth)
    assert r.status_code == 200
    assert r.json()["job"]["status"] == "done"
    assert r.json()["job"]["completed_at"] is not None


def test_review_approve_409_without_ready_mp4_or_not_inspect(api, auth, db):
    pending = inspect_job(db, mp4_status="pending")
    assert api.post(f"{URL}/{pending['id']}/review/approve", headers=auth).status_code == 409
    old_rev = inspect_job(db)
    db.add_revision(old_rev, rev_no=2, approved=True)  # 새 승인본에는 done run 없음
    assert api.post(f"{URL}/{old_rev['id']}/review/approve", headers=auth).status_code == 409
    review = db.add_job(status="review")
    assert api.post(f"{URL}/{review['id']}/review/approve", headers=auth).status_code == 409


# === A-18 다운로드 ============================================================


def test_download_url_600s_and_ready_only(api, auth, db):
    job = db.add_job(status="inspect")
    ready = db.add_asset(job, "output_mp4")
    pending = db.add_asset(job, "report", status="pending")
    before = datetime.now(UTC)
    r = api.get(f"{URL}/{job['id']}/assets/{ready['id']}/download-url", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "output_mp4"
    assert body["url"].startswith(
        f"{STORAGE}/object/sign/production/{ready['storage_path']}?token="
    )
    expires = datetime.fromisoformat(body["expires_at"])
    assert timedelta(seconds=595) <= expires - before <= timedelta(seconds=605)
    assert r.headers["cache-control"] == "no-store"
    r = api.get(f"{URL}/{job['id']}/assets/{pending['id']}/download-url", headers=auth)
    assert r.status_code == 409


# === 로그: 서명 URL 토큰 0건 ===================================================


def test_logs_never_contain_signed_url_tokens(api, auth, db, caplog):
    stream = io.StringIO()
    handler = setup_logging(stream)
    caplog.set_level(logging.DEBUG)
    try:
        job = db.add_job()
        asset = upload(api, auth, job["id"], size=10).json()["asset"]
        db.objects[db.assets[0]["storage_path"]] = 10
        api.post(f"{URL}/{job['id']}/uploads/{asset['id']}/complete", headers=auth)
        out = db.add_job(status="inspect")
        mp4 = db.add_asset(out, "output_mp4")
        api.get(f"{URL}/{out['id']}/assets/{mp4['id']}/download-url", headers=auth)
        # 저장소 오류 경로도 로그에 URL을 남기지 않는다
        db.objects.clear()
        api.post(f"{URL}/{job['id']}/uploads/{asset['id']}/complete", headers=auth)
    finally:
        handler.setStream(sys.stderr)
    assert len(db.issued_tokens) == 2
    logged = caplog.text + stream.getvalue()
    assert "제작 작업" in logged or "업로드" in logged
    for token in db.issued_tokens:
        sig = token.rsplit(".", 1)[1]
        assert token not in logged and sig not in logged
    assert "token=" not in logged


def test_storage_failure_is_503_without_url(api, auth, db, mock_supabase):
    mock_supabase.post(url__startswith=f"{STORAGE}/object/sign/production/").mock(
        return_value=httpx.Response(500, json={"message": "boom"})
    )
    job = db.add_job(status="inspect")
    mp4 = db.add_asset(job, "output_mp4")
    r = api.get(f"{URL}/{job['id']}/assets/{mp4['id']}/download-url", headers=auth)
    assert r.status_code == 503
    assert "production" not in r.text


# === 리뷰 반영(🟡1~4) ==========================================================


def test_review_size_mismatch_deletes_object_and_pending_row(api, auth, db):
    job = db.add_job()
    asset = upload(api, auth, job["id"], size=1234).json()["asset"]
    path = db.assets[0]["storage_path"]
    db.objects[path] = 999
    r = api.post(f"{URL}/{job['id']}/uploads/{asset['id']}/complete", headers=auth)
    assert r.status_code == 409 and r.json()["field"] == "size_bytes"
    assert path not in db.objects and db.assets == []
    # 다시 업로드 요청부터 진행할 수 있다
    assert upload(api, auth, job["id"], size=999).status_code == 201


def test_review_new_hook_audio_replaces_pending_hook_audio(api, auth, db):
    job = db.add_job(status="review")
    old = db.add_asset(job, "hook_audio", status="pending", mime="audio/wav")
    kept = db.add_asset(job, "hook_audio", status="ready", mime="audio/wav")
    db.objects[old["storage_path"]] = 10
    assert upload(api, auth, job["id"], kind="hook_audio", mime="audio/wav").status_code == 201
    assert old not in db.assets and old["storage_path"] not in db.objects
    assert kept in db.assets
    assert len([a for a in db.assets if a["kind"] == "hook_audio"]) == 2


def test_review_concurrent_complete_second_ready_source_409(api, auth, db):
    job = db.add_job()
    first = db.add_asset(job, "source_upload", status="pending", size_bytes=10)
    second = db.add_asset(job, "source_upload", status="pending", size_bytes=10)
    db.objects[first["storage_path"]] = 10
    db.objects[second["storage_path"]] = 10
    ok = api.post(f"{URL}/{job['id']}/uploads/{first['id']}/complete", headers=auth)
    assert ok.status_code == 200
    # 앞선 ready 확인 조회를 지나친 경합: DB 부분 unique가 막고 API는 409
    db.hide_ready_source = True
    r = api.post(f"{URL}/{job['id']}/uploads/{second['id']}/complete", headers=auth)
    assert r.status_code == 409
    assert r.json()["message"] == "이미 업로드된 원본이 있습니다."
    assert second["status"] == "pending"


def test_review_patch_and_review_approve_record_updated_at(api, auth, db):
    job = db.add_job()
    r = api.patch(f"{URL}/{job['id']}", json={"segment_len_sec": 30}, headers=auth)
    assert datetime.fromisoformat(r.json()["job"]["updated_at"]) > datetime.now(UTC) - timedelta(
        minutes=1
    )
    done = inspect_job(db)
    r = api.post(f"{URL}/{done['id']}/review/approve", headers=auth)
    out = r.json()["job"]
    assert out["updated_at"] == out["completed_at"]


# === task-035 예능형(variety) API 연결 ============================================

VARIETY_META = {"duration_sec": 60.0, "width": 1920, "height": 1080, "has_audio": True}


def variety_job(db: FakeDB, **over: Any) -> dict:
    over.setdefault("status", "review")
    over.setdefault("source_meta", VARIETY_META)
    return db.add_job(format="variety", preset_version="variety-1080-v1", **over)


def vspec() -> dict:
    spec = variety_good()
    spec["source_start_sec"] = 0
    spec["preset_version"] = "variety-1080-v1"
    return spec


def test_v_create_variety_job_201_with_variety_preset(api, auth, db):
    r = post_job(api, auth, format="variety")
    assert r.status_code == 201
    job = r.json()["job"]
    assert job["format"] == "variety" and job["preset_version"] == "variety-1080-v1"
    assert db.jobs[0]["format"] == "variety"


def test_v3_same_key_other_format_returns_existing_200(api, auth, db):
    assert post_job(api, auth, key="vk-1").status_code == 201
    r = post_job(api, auth, key="vk-1", format="variety")
    assert r.status_code == 200 and r.json()["job"]["format"] == "category"
    assert len(db.jobs) == 1


def test_v_patch_format_change_rejected_400_and_unchanged(api, auth, db):
    job = variety_job(db, status="draft")
    r = api.patch(f"{URL}/{job['id']}", json={"format": "category"}, headers=auth)
    assert r.status_code == 400
    assert r.json()["code"] == "VALIDATION" and r.json()["field"] == "format"
    assert job["format"] == "variety"


def test_v_list_filter_by_format_and_item_format(api, auth, db):
    db.add_job(title="c")
    variety_job(db, title="v")
    r = api.get(URL, params={"format": "variety"}, headers=auth)
    assert [(i["title"], i["format"]) for i in r.json()["items"]] == [("v", "variety")]


def test_v_put_variety_spec_valid_saves_with_warnings_only(api, auth, db):
    job = variety_job(db)
    rev = db.add_revision(job, spec={})
    r = put_rev(api, auth, job["id"], vspec())
    assert r.status_code == 200
    v = r.json()["revision"]["validation"]
    assert v["errors"] == [] and [w["code"] for w in v["warnings"]] == ["cuts.short"]
    assert rev["spec"] == vspec()


def test_v_put_variety_semantic_errors_saved(api, auth, db):
    job = variety_job(db)
    rev = db.add_revision(job, spec={})
    spec = vspec()
    spec["cuts"][0]["x"] = 900  # 빈 화면
    spec["subtitles"][1]["start"] = 1.0  # 자막 겹침
    spec["preset_version"] = "category-1080-v1"
    r = put_rev(api, auth, job["id"], spec)
    assert r.status_code == 200
    codes = {e["code"] for e in r.json()["revision"]["validation"]["errors"]}
    assert {"cuts.empty_area", "subtitles.overlap", "preset_version.mismatch"} <= codes
    assert rev["spec"] == spec


def test_v4_segment_len_is_min_of_job_segment_and_source_duration(api, auth, db):
    job = variety_job(db, segment_len_sec=60)
    db.add_revision(job, spec={})
    db.add_asset(job, "source", duration_sec=40)  # 컷 끝 48.6 > 40
    r = put_rev(api, auth, job["id"], vspec())
    assert "cuts.out_of_range" in [e["code"] for e in r.json()["revision"]["validation"]["errors"]]
    short = variety_job(db, segment_len_sec=45)  # 원본 길이 없음 → 작업 구간 45
    db.add_revision(short, spec={})
    r = put_rev(api, auth, short["id"], vspec())
    assert "cuts.out_of_range" in [e["code"] for e in r.json()["revision"]["validation"]["errors"]]


def test_v4_source_size_missing_is_error_and_blocks_approve(api, auth, db):
    job = variety_job(db, source_meta=None)
    db.add_revision(job, spec={})
    r = put_rev(api, auth, job["id"], vspec())
    assert r.status_code == 200
    errors = r.json()["revision"]["validation"]["errors"]
    assert [(e["code"], e["path"]) for e in errors] == [("source_size.missing", "source_size")]
    r = approve(api, auth, job["id"])
    assert r.status_code == 400
    assert [e["code"] for e in r.json()["errors"]] == ["source_size.missing"]


def test_v4_source_size_used_for_empty_area(api, auth, db):
    # 배율 1·이동 0 컷: 세로 원본(1080x1920)은 띠를 덮고, 가로(1920x1080)는 높이 607px라 빈 화면
    spec = vspec()
    for c in spec["cuts"]:
        c.update(scale=1, x=0, y=0)
    portrait = variety_job(db, source_meta={**VARIETY_META, "width": 1080, "height": 1920})
    db.add_revision(portrait, spec={})
    r = put_rev(api, auth, portrait["id"], spec)
    assert r.json()["revision"]["validation"]["errors"] == []
    landscape = variety_job(db)
    db.add_revision(landscape, spec={})
    r = put_rev(api, auth, landscape["id"], spec)
    codes = {e["code"] for e in r.json()["revision"]["validation"]["errors"]}
    assert codes == {"cuts.empty_area"}


def test_v_put_category_spec_on_variety_job_400_not_saved(api, auth, db):
    job = variety_job(db)
    rev = db.add_revision(job, spec={})
    r = put_rev(api, auth, job["id"], good_spec())
    assert r.status_code == 400
    assert all(e["code"].startswith("schema.") for e in r.json()["errors"])
    assert rev["spec"] == {}
    assert "save" not in db.rpc_calls


def test_v_category_job_rejects_variety_spec(api, auth, db):
    job = db.add_job(status="review")
    db.add_revision(job)
    r = put_rev(api, auth, job["id"], vspec())
    assert r.status_code == 400
    assert all(e["code"].startswith("schema.") for e in r.json()["errors"])


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("header", "lines", 0), "제목\u0000"),
        (("subtitles", 0, "text"), "대사\u0007"),
        (("reactions", 0, "text"), "\u001b[31m반응"),
        (("subtitles", 0, "text"), "탭\t문자"),
        (("reactions", 0, "text"), "끝\u007f"),
    ],
)
def test_v6_control_chars_rejected_400_not_saved(api, auth, db, path, value):
    job = variety_job(db)
    rev = db.add_revision(job, spec={})
    spec = vspec()
    _set(spec, path, value)
    r = put_rev(api, auth, job["id"], spec)
    assert r.status_code == 400
    assert [e["code"] for e in r.json()["errors"]] == ["schema.value_error"]
    assert value not in r.text  # 입력 값은 응답에 없음
    assert rev["spec"] == {}


def test_v6_header_newline_stays_header_invalid(api, auth, db):
    job = variety_job(db)
    db.add_revision(job, spec={})
    spec = vspec()
    spec["header"]["lines"] = ["한 줄\n두 줄"]
    r = put_rev(api, auth, job["id"], spec)
    assert r.status_code == 200
    codes = [e["code"] for e in r.json()["revision"]["validation"]["errors"]]
    assert codes == ["header.invalid"]


def _sub(i: int) -> dict:
    return {"start": i * 0.2, "end": i * 0.2 + 0.1, "style": "line", "text": "a"}


def _react(i: int) -> dict:
    return {"start": 0, "end": 1, "text": "r", "x": 1, "y": 1}


@pytest.mark.parametrize(("field_name", "make"), [("subtitles", _sub), ("reactions", _react)])
def test_v6_subtitles_reactions_count_cap_200(api, auth, db, field_name, make):
    job = variety_job(db)
    db.add_revision(job, spec={})
    spec = vspec()
    spec[field_name] = [make(i) for i in range(201)]
    r = put_rev(api, auth, job["id"], spec)
    assert r.status_code == 400
    assert [(e["code"], e["path"]) for e in r.json()["errors"]] == [("schema.too_long", field_name)]
    spec[field_name] = spec[field_name][:200]
    assert put_rev(api, auth, job["id"], spec).status_code == 200


def _set(spec: dict, path: tuple, value: Any) -> None:
    target: Any = spec
    for k in path[:-1]:
        target = target[k]
    target[path[-1]] = value


@pytest.mark.parametrize(
    ("path", "limit"),
    [
        (("header", "lines", 0), 60),
        (("subtitles", 0, "text"), 200),
        (("reactions", 0, "text"), 200),
    ],
)
def test_v6_text_length_caps(api, auth, db, path, limit):
    job = variety_job(db)
    db.add_revision(job, spec={})
    spec = vspec()
    _set(spec, path, "가" * (limit + 1))
    r = put_rev(api, auth, job["id"], spec)
    assert r.status_code == 400
    assert [e["code"] for e in r.json()["errors"]] == ["schema.string_too_long"]
    _set(spec, path, "가" * limit)
    assert put_rev(api, auth, job["id"], spec).status_code == 200


def test_v_approve_variety_ok_when_no_errors(api, auth, db):
    job = variety_job(db)
    rev = db.add_revision(job, spec=vspec())
    r = approve(api, auth, job["id"])
    assert r.status_code == 200
    assert rev["approved_at"] is not None


def test_v_approve_variety_with_errors_400_revalidates(api, auth, db):
    job = variety_job(db)
    spec = vspec()
    spec["cuts"][0]["src_end"] = spec["cuts"][0]["src_start"] + 0.1  # 0.2초 미만
    rev = db.add_revision(job, spec=spec, validation={"errors": [], "warnings": []})
    r = approve(api, auth, job["id"])
    assert r.status_code == 400
    assert "cuts.too_short" in [e["code"] for e in r.json()["errors"]]
    assert rev["approved_at"] is None
    assert "approve" not in db.rpc_calls


# --- task-035 리뷰 반영: 보이지 않는 문자·컷 개수 스키마 상한 ---


@pytest.mark.parametrize(
    "ch",
    [
        "\u0080",  # C1 시작
        "\u0085",  # NEL
        "\u009f",  # C1 끝
        "​",  # 제로폭 공백
        "‌",
        "‍",
        "‎",  # LRM
        "‏",  # RLM
        "‪",  # LRE
        "‫",
        "‬",
        "‭",
        "‮",  # RLO
        "⁦",  # LRI
        "⁧",
        "⁨",
        "⁩",  # PDI
        "﻿",  # BOM
        " ",  # 줄 구분
        " ",  # 문단 구분
    ],
)
@pytest.mark.parametrize(
    "path", [("header", "lines", 0), ("subtitles", 0, "text"), ("reactions", 0, "text")]
)
def test_review_invisible_chars_rejected_400(api, auth, db, ch, path):
    job = variety_job(db)
    rev = db.add_revision(job, spec={})
    spec = vspec()
    _set(spec, path, f"문구{ch}끝")
    r = put_rev(api, auth, job["id"], spec)
    assert r.status_code == 400
    assert [e["code"] for e in r.json()["errors"]] == ["schema.value_error"]
    assert rev["spec"] == {}


def test_review_cuts_over_60_rejected_at_schema(api, auth, db):
    job = variety_job(db)
    rev = db.add_revision(job, spec={})
    spec = vspec()
    spec["cuts"] = [dict(spec["cuts"][0]) for _ in range(61)]
    r = put_rev(api, auth, job["id"], spec)
    assert r.status_code == 400
    assert [(e["code"], e["path"]) for e in r.json()["errors"]] == [("schema.too_long", "cuts")]
    assert rev["spec"] == {}
    spec["cuts"] = spec["cuts"][:60]
    spec["subtitles"], spec["reactions"] = [], []
    assert put_rev(api, auth, job["id"], spec).status_code == 200
