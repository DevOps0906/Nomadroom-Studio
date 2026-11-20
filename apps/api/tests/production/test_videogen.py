"""task-054 AI 영상 생성(A-22) 테스트. 실제 xAI 호출 없음(G0).

- 플랫폼은 모의 어댑터(dependency_overrides) 또는 respx로 막은 XaiAdapter만 쓴다.
- 가짜 PostgREST·Storage는 test_jobs_api의 FakeDB를 잇고, RPC는
  supabase/migrations/20261120000026_generation_runs.sql을 본뜬다(월 경계·잠금 등 실제 SQL은
  supabase/tests/production_generation_runs_test.sql이 검사).
"""

import base64
import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.main import create_app
from app.production import shopping, videogen
from app.production.validation_shopping import validate_shopping_spec
from app.production.videogen import download
from app.production.videogen.base import PollResult, Rejected, Unknown
from app.production.videogen.xai import API_BASE, XaiAdapter
from tests.conftest import JWKS_URL, make_settings
from tests.production import test_validation_shopping as vs
from tests.production.test_jobs_api import (
    OTHER_WS,
    REST,
    STORAGE,
    URL,
    USER,
    WS,
    FakeDB,
    _now,
    _params,
    _rpc_error,
    _select,
    install,
)

MEMBER = "22222222-2222-4222-8222-222222222222"
JPEG = b"\xff\xd8\xff\xe0" + b"photo-bytes"
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64
RESULT_URL = "https://vidgen.x.ai/out/abc.mp4"
PUBLIC_IP = "93.184.216.34"
XAI_KEY = "xai-test-" + "k" * 24


# --- 모의 플랫폼 -----------------------------------------------------------------------


class FakeAdapter:
    platform = "xai"
    model = "grok-imagine-video"
    result_hosts = frozenset({"vidgen.x.ai"})

    def __init__(self) -> None:
        self.submits: list[dict] = []
        self.polls: list[str] = []
        self.submit_error: Exception | None = None
        self.poll_result: PollResult | Exception = PollResult("pending")

    def estimate_usd(self, duration_sec: int) -> Decimal:
        return Decimal("0.08") * duration_sec

    async def submit(self, image: bytes, mime: str, prompt: str, duration_sec: int) -> str:
        self.submits.append({"image": image, "mime": mime, "prompt": prompt, "d": duration_sec})
        if self.submit_error is not None:
            raise self.submit_error
        return "req-1"

    async def poll(self, request_id: str) -> PollResult:
        self.polls.append(request_id)
        if isinstance(self.poll_result, Exception):
            raise self.poll_result
        return self.poll_result


# --- 가짜 DB(000026 RPC 본뜸) -------------------------------------------------------------


def _ok(body: Any) -> httpx.Response:
    return httpx.Response(200, json=body)


@dataclass
class GenDB(FakeDB):
    gen_runs: list[dict] = field(default_factory=list)
    budget: int = 10_000
    cap: int = 6_000
    owners: set[str] = field(default_factory=lambda: {USER})
    blobs: dict[str, bytes] = field(default_factory=dict)
    claim_taken: bool = False  # 다른 요청이 먼저 완료 처리를 선점한 상황
    reject_result: bool = False  # 000023 트리거가 결과 저장을 거부하는 상황
    mark_failures: int = 0  # running 제출 기록 RPC를 이 횟수만큼 500으로
    finish_lost_response: bool = False  # finish는 저장됐는데 응답만 500
    fail_rpc: str | None = None  # 이 RPC는 500(저장소 오류)

    def _expire_stalled(self, r: dict) -> None:
        """000026 _gen_expire_stalled: confirmed·request_id 없음·확인 후 5분 → unknown."""
        stalled = datetime.now(UTC) - timedelta(minutes=5)
        if (
            r["status"] == "confirmed"
            and r["request_id"] is None
            and datetime.fromisoformat(r["confirmed_at"]) < stalled
        ):
            r.update(status="unknown", error_code="submit_stalled")

    uploads: list[str] = field(default_factory=list)

    @staticmethod
    def _cost(r: dict) -> int:
        return r["actual_cost_krw"] if r["actual_cost_krw"] is not None else r["est_cost_krw"]

    def budget_json(self, job_id: str) -> dict:
        billed = [r for r in self.gen_runs if r["billable"]]
        return {
            "monthly_budget_krw": self.budget,
            "job_cap_krw": self.cap,
            "monthly_left_krw": self.budget - sum(self._cost(r) for r in billed),
            "job_left_krw": self.cap - sum(self._cost(r) for r in billed if r["job_id"] == job_id),
        }

    def _require(self, job_id: str, est: int) -> httpx.Response | None:
        b = self.budget_json(job_id)
        left = min(b["monthly_left_krw"], b["job_left_krw"])
        if self.budget <= 0 or self.cap <= 0 or est > left:
            return httpx.Response(
                400, json={"code": "NR019", "message": "x", "details": str(max(left, 0))}
            )
        return None

    def _source_ok(self, ws: str, job_id: str, asset_id: str | None) -> bool:
        a = next(
            (
                a
                for a in self.assets
                if a["id"] == asset_id and a["job_id"] == job_id and a["workspace_id"] == ws
            ),
            None,
        )
        rights = (a or {}).get("rights") or {}
        return (
            a is not None
            and a["kind"] == "image"
            and a["status"] == "ready"
            and rights.get("basis") in ("own", "licensed")
        )

    @staticmethod
    def _prepare_state(j: dict) -> bool:
        return j["status"] == "draft" or (
            j["status"] == "failed" and j.get("failed_stage") == "prepare"
        )

    def _run(self, body: dict, with_job: bool = True) -> dict | None:
        return next(
            (
                r
                for r in self.gen_runs
                if r["id"] == body["p_run"]
                and r["workspace_id"] == body["p_workspace"]
                and (not with_job or r["job_id"] == body["p_job"])
            ),
            None,
        )

    @staticmethod
    def _out(r: dict) -> dict:
        return {k: v for k, v in r.items() if k != "idempotency_key"}

    def quote(self, body: dict) -> httpx.Response:
        self.rpc_calls.append("quote")
        j = self._locked_job(body)
        if j is None:
            return _rpc_error("NR009")
        old = next(
            (
                r
                for r in self.gen_runs
                if r["workspace_id"] == body["p_workspace"]
                and r["idempotency_key"] == body["p_key"]
            ),
            None,
        )
        if old is not None:
            if old["job_id"] != body["p_job"]:
                return _rpc_error("NR011")
            return _ok({"replay": True, "run": self._out(old), "budget": self.budget_json(j["id"])})
        if j.get("kind") != "shopping" or not self._prepare_state(j):
            return _rpc_error("NR010")
        if not self._source_ok(body["p_workspace"], j["id"], body["p_source_asset"]):
            return _rpc_error("NR012")
        if (err := self._require(j["id"], body["p_est_cost"])) is not None:
            return err
        run = {
            "id": str(uuid.uuid4()),
            "workspace_id": body["p_workspace"],
            "job_id": j["id"],
            "source_asset_id": body["p_source_asset"],
            "result_asset_id": None,
            "cut_ref": body["p_cut_ref"],
            "prompt": body["p_prompt"],
            "platform": body["p_platform"],
            "model": body["p_model"],
            "duration_sec": body["p_duration"],
            "est_cost_krw": body["p_est_cost"],
            "actual_cost_krw": None,
            "billable": False,
            "status": "quoted",
            "error_code": None,
            "request_id": None,
            "idempotency_key": body["p_key"],
            "requested_by": body["p_user"],
            "confirmed_by": None,
            "created_at": _now(),
            "confirmed_at": None,
            "finished_at": None,
        }
        self.gen_runs.append(run)
        return _ok({"replay": False, "run": self._out(run), "budget": self.budget_json(j["id"])})

    def confirm(self, body: dict) -> httpx.Response:
        self.rpc_calls.append("confirm")
        if body["p_user"] not in self.owners:
            return _rpc_error("NR020")
        j = self._locked_job(body)
        r = self._run(body)
        if j is None or r is None:
            return _rpc_error("NR009")
        if r["status"] != "quoted":
            self._expire_stalled(r)
            return _ok({"replay": True, "run": self._out(r), "budget": self.budget_json(j["id"])})
        if not self._prepare_state(j):
            return _rpc_error("NR010")
        if not self._source_ok(body["p_workspace"], j["id"], r["source_asset_id"]):
            return _rpc_error("NR012")
        if (err := self._require(j["id"], r["est_cost_krw"])) is not None:
            return err
        r.update(status="confirmed", billable=True, confirmed_by=body["p_user"])
        r["confirmed_at"] = _now()
        return _ok({"replay": False, "run": self._out(r), "budget": self.budget_json(j["id"])})

    def mark(self, body: dict) -> httpx.Response:
        self.rpc_calls.append("mark:" + body["p_outcome"])
        r = self._run(body, with_job=False)
        if r is None:
            return _rpc_error("NR009")
        if r["status"] != "confirmed":
            return _rpc_error("NR010")
        if body["p_outcome"] == "running" and self.mark_failures > 0:
            self.mark_failures -= 1
            return httpx.Response(500, json={"message": "x"})
        if body["p_outcome"] == "running" and body["p_request_id"]:
            r.update(status="running", request_id=body["p_request_id"])
        elif body["p_outcome"] == "unknown":
            r.update(status="unknown", error_code=body["p_error"])
        elif body["p_outcome"] == "rejected":
            r.update(status="failed", billable=False, error_code=body["p_error"])
        else:
            return _rpc_error("NR012")
        return _ok(self._out(r))

    def begin(self, body: dict) -> httpx.Response:
        self.rpc_calls.append("begin")
        r = self._run(body)
        if r is None:
            return _rpc_error("NR009")
        self._expire_stalled(r)
        return _ok(self._out(r))

    def claim(self, body: dict) -> httpx.Response:
        self.rpc_calls.append("claim")
        r = self._run(body, with_job=False)
        if self.claim_taken or r is None or r["status"] != "running":
            return httpx.Response(200, content=b"null")
        r.update(status="finalizing", finalize_token=str(uuid.uuid4()))
        return _ok({**self._out(r), "finalize_token": r["finalize_token"]})

    def finish(self, body: dict) -> httpx.Response:
        self.rpc_calls.append("finish:" + body["p_status"])
        r = self._run(body, with_job=False)
        if r is None:
            return _rpc_error("NR009")
        if r["status"] != "finalizing" or r.get("finalize_token") != body["p_token"]:
            return _rpc_error("NR010")
        r["actual_cost_krw"] = body["p_actual_cost"]
        if body["p_status"] == "failed":
            r.update(status="failed", error_code=body["p_error"])
            return _ok({"run": self._out(r), "rejected": False})
        if self.reject_result:
            r.update(status="failed", error_code="result_rejected")
            return _ok({"run": self._out(r), "rejected": True})
        src = next((a for a in self.assets if a["id"] == r["source_asset_id"]), None)
        rights = {k: v for k, v in ((src or {}).get("rights") or {}).items() if k != "gen"}
        rights.update(
            basis="ai_generated",
            gen={
                "platform": r["platform"],
                "model": r["model"],
                "request_id": r["request_id"],
                "cost_krw": self._cost(r),
            },
        )
        job = next(j for j in self.jobs if j["id"] == r["job_id"])
        self.add_asset(
            job,
            "source_upload",
            id=body["p_asset"],
            storage_path=body["p_path"],
            size_bytes=body["p_size"],
            rights=rights,
            reviewed=False,
            review_checks=None,
        )
        r.update(status="done", result_asset_id=body["p_asset"])
        if self.finish_lost_response:
            return httpx.Response(500, json={"message": "x"})
        return _ok({"run": self._out(r), "rejected": False})

    def review(self, body: dict) -> httpx.Response:
        r = self._run(body)
        if r is None:
            return _rpc_error("NR009")
        if r["status"] != "done" or not r["result_asset_id"]:
            return _rpc_error("NR010")
        c = body["p_checks"]
        ok = bool(c["physics"] and c["angle"] and c["compare"])
        checks = {**c, "reviewed_by": body["p_user"], "reviewed_at": _now()}
        asset = next(a for a in self.assets if a["id"] == r["result_asset_id"])
        asset.update(reviewed=ok, review_checks=checks)
        return _ok({"run": self._out(r), "reviewed": ok, "review_checks": checks})

    # --- Storage ---
    def object_get(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.split("/object/authenticated/production/", 1)[1]
        return (
            httpx.Response(200, content=self.blobs[path])
            if path in self.blobs
            else httpx.Response(400, json={"statusCode": "404"})
        )

    def upload(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.split("/storage/v1/object/production/", 1)[1]
        assert request.headers["x-upsert"] == "false"
        self.uploads.append(path)
        self.objects[path] = len(request.content)
        return httpx.Response(200, json={"Key": path})


# --- 픽스처 ---------------------------------------------------------------------------


@pytest.fixture
def db() -> GenDB:
    return GenDB()


@pytest.fixture
def adapter() -> FakeAdapter:
    return FakeAdapter()


@pytest.fixture(autouse=True)
def public_dns(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """결과 호스트 DNS는 공인 IP로 고정(실제 DNS 조회 없음)."""
    answer = [PUBLIC_IP]

    async def fake(host: str) -> list[str]:
        return list(answer)

    monkeypatch.setattr(download, "resolve", fake)
    return answer


def _install(router: respx.MockRouter, jwks_payload: dict, db: GenDB) -> None:
    router.get(JWKS_URL).mock(return_value=httpx.Response(200, json=jwks_payload))
    router.get(f"{REST}/workspace_members").mock(
        return_value=httpx.Response(200, json=[{"workspace_id": WS}])
    )
    install(router, db)
    router.get(f"{REST}/generation_runs").mock(
        side_effect=lambda r: _ok(_select(db.gen_runs, _params(r)))
    )

    def call(request: httpx.Request, name: str, attr: str) -> httpx.Response:
        if db.fail_rpc == name:
            return httpx.Response(500, json={"message": "x"})
        return getattr(db, attr)(json.loads(request.content))  # 테스트가 메서드를 바꿔 끼울 수 있게

    for name, attr in (
        ("quote_generation_run", "quote"),
        ("confirm_generation_run", "confirm"),
        ("mark_generation_submitted", "mark"),
        ("begin_generation_refresh", "begin"),
        ("claim_generation_finalize", "claim"),
        ("finish_generation_run", "finish"),
        ("review_generation_run", "review"),
    ):
        router.post(f"{REST}/rpc/{name}").mock(side_effect=lambda r, n=name, a=attr: call(r, n, a))
    router.get(url__startswith=f"{STORAGE}/object/authenticated/production/").mock(
        side_effect=db.object_get
    )
    router.post(url__startswith=f"{STORAGE}/object/production/").mock(side_effect=db.upload)


def _client(router, jwks_payload, db, adapter=None, **settings: Any) -> TestClient:
    _install(router, jwks_payload, db)
    app = create_app(make_settings(**settings))
    if adapter is not None:
        app.dependency_overrides[videogen.get_adapter] = lambda: adapter
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def api(mock_supabase, jwks_payload, db, adapter) -> Iterator[TestClient]:
    with _client(
        mock_supabase,
        jwks_payload,
        db,
        adapter,
        videogen_enabled=True,
        videogen_xai_api_key=XAI_KEY,
    ) as c:
        yield c
    hosts = {call.request.url.host for call in mock_supabase.calls}
    assert hosts <= {"supabase.test", "vidgen.x.ai"}, hosts  # xAI API 호출 없음


@pytest.fixture
def auth(make_token) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token()}"}


def shop_job(db: GenDB, **over: Any) -> tuple[dict, dict]:
    job = db.add_job(kind="shopping", format="shopping", vertical="travel", **over)
    img = db.add_asset(job, "image", mime="image/jpeg", rights={"basis": "own", "author": "운영자"})
    img["storage_path"] = f"{job['workspace_id']}/{job['id']}/{img['id']}.jpg"
    db.blobs[img["storage_path"]] = JPEG
    return job, img


def quote(api, auth, job, img, key="g-1", **over: Any) -> httpx.Response:
    body = {"source_asset_id": img["id"], "prompt": "노을 지는 바다 위 숙소", "duration_sec": 5}
    body.update(over)
    return api.post(
        f"{URL}/{job['id']}/generation-runs", json=body, headers={**auth, "Idempotency-Key": key}
    )


def confirm(api, auth, job, run_id) -> httpx.Response:
    return api.post(f"{URL}/{job['id']}/generation-runs/{run_id}/confirm", headers=auth)


def refresh(api, auth, job, run_id) -> httpx.Response:
    return api.post(f"{URL}/{job['id']}/generation-runs/{run_id}/refresh", headers=auth)


def running_run(api, auth, db, job, img) -> str:
    run_id = quote(api, auth, job, img).json()["run"]["id"]
    assert confirm(api, auth, job, run_id).status_code == 202
    return run_id


# --- 기본 꺼짐(G0·G9) -------------------------------------------------------------------


@pytest.mark.parametrize(
    "settings",
    [{}, {"videogen_enabled": True}, {"videogen_xai_api_key": XAI_KEY}],
    ids=["default", "no_key", "not_enabled"],
)
def test_disabled_503_without_records(mock_supabase, jwks_payload, db, auth, settings):
    job, img = shop_job(db)
    with _client(mock_supabase, jwks_payload, db, **settings) as api:
        r = quote(api, auth, job, img)
        assert r.status_code == 503 and r.json()["code"] == "UPSTREAM_ERROR"
        assert confirm(api, auth, job, uuid.uuid4()).status_code == 503
        assert refresh(api, auth, job, uuid.uuid4()).status_code == 503
    assert db.rpc_calls == [] and db.gen_runs == []


def test_blank_key_is_missing():
    assert make_settings(videogen_xai_api_key="  ").videogen_xai_api_key is None
    s = make_settings(videogen_xai_api_key=XAI_KEY)
    assert XAI_KEY not in repr(s) and XAI_KEY not in str(s.model_dump())
    assert make_settings().videogen_enabled is False


def test_real_adapter_quote_estimates_without_platform_call(mock_supabase, jwks_payload, db, auth):
    job, img = shop_job(db)
    with _client(
        mock_supabase, jwks_payload, db, videogen_enabled=True, videogen_xai_api_key=XAI_KEY
    ) as api:
        r = quote(api, auth, job, img, duration_sec=5)
    assert r.status_code == 201, r.text
    run = r.json()["run"]
    assert run["platform"] == "xai" and run["est_cost_krw"] == 580  # 0.08*5*1450=580
    assert all(c.request.url.host == "supabase.test" for c in mock_supabase.calls)


# --- 견적 ---------------------------------------------------------------------------------


def test_quote_201_then_same_key_200_same_run(api, auth, db):
    job, img = shop_job(db)
    r = quote(api, auth, job, img, duration_sec=7, cut_ref="3")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["run"]["status"] == "quoted" and body["run"]["billable"] is False
    assert body["run"]["est_cost_krw"] == 812  # ceil(0.56*1450)=812
    assert body["budget"] == {"monthly_left_krw": 10_000, "job_left_krw": 6_000}
    again = quote(api, auth, job, img, prompt="다른 문구")
    assert again.status_code == 200 and again.json()["replay"] is True
    assert again.json()["run"]["id"] == body["run"]["id"] and len(db.gen_runs) == 1


def test_est_cost_rounds_up():
    assert videogen.krw(Decimal("0.08"), 1450) == 116
    assert videogen.krw(Decimal("0.0801"), 1450) == 117  # 116.145 → 117
    assert videogen.krw(Decimal("0"), 1450) == 1  # 최소 1원


@pytest.mark.parametrize("budget,cap", [(0, 6_000), (10_000, 0)])
def test_zero_budget_rejected_409(api, auth, db, budget, cap):
    db.budget, db.cap = budget, cap
    job, img = shop_job(db)
    r = quote(api, auth, job, img)
    assert r.status_code == 409
    assert r.json()["field"] == "budget_exceeded" and r.json()["remaining_krw"] == 0
    assert db.gen_runs == []


def test_quote_over_job_cap_409_with_remaining(api, auth, db):
    db.cap = 500
    job, img = shop_job(db)
    r = quote(api, auth, job, img, duration_sec=5)  # 580원 > 500원
    assert r.status_code == 409 and r.json()["remaining_krw"] == 500


@pytest.mark.parametrize(
    "body",
    [
        {"duration_sec": 0},
        {"duration_sec": 16},
        {"duration_sec": "5"},
        {"prompt": ""},
        {"prompt": "가" * 501},
        {"prompt": "줄‮바꿈"},
        {"extra": 1},
    ],
)
def test_quote_input_400(api, auth, db, body):
    job, img = shop_job(db)
    assert quote(api, auth, job, img, **body).status_code == 400
    assert db.rpc_calls == []


def test_quote_rights_missing_400_and_state_409(api, auth, db):
    job, img = shop_job(db)
    img["rights"] = None
    r = quote(api, auth, job, img)
    assert r.status_code == 400 and r.json()["field"] == "source_asset_id"
    job2, img2 = shop_job(db, status="review")
    assert quote(api, auth, job2, img2, key="g-2").status_code == 409
    job3, img3 = shop_job(db, status="failed", failed_stage="prepare")
    assert quote(api, auth, job3, img3, key="g-3").status_code == 201


def test_quote_missing_key_400(api, auth, db):
    job, img = shop_job(db)
    r = api.post(
        f"{URL}/{job['id']}/generation-runs",
        json={"source_asset_id": img["id"], "prompt": "p", "duration_sec": 3},
        headers=auth,
    )
    assert r.status_code == 400 and r.json()["field"] == "Idempotency-Key"


def test_other_workspace_job_404(api, auth, db):
    job, img = shop_job(db, ws=OTHER_WS)
    assert quote(api, auth, job, img).status_code == 404


# --- 확인·제출(G2·G6·G7) -----------------------------------------------------------------


def test_confirm_submits_photo_as_body_and_runs(api, auth, db, adapter):
    job, img = shop_job(db)
    run_id = quote(api, auth, job, img).json()["run"]["id"]
    r = confirm(api, auth, job, run_id)
    assert r.status_code == 202, r.text
    assert r.json()["run"]["status"] == "running" and r.json()["run"]["request_id"] == "req-1"
    assert adapter.submits == [
        {"image": JPEG, "mime": "image/jpeg", "prompt": "노을 지는 바다 위 숙소", "d": 5}
    ]
    assert db.issued_tokens == []  # 서명 URL을 만들지 않음(외부에 넘기지 않음)
    assert db.budget_json(job["id"])["job_left_krw"] == 6_000 - 580


def test_reconfirm_returns_current_run_without_charge(api, auth, db, adapter):
    job, img = shop_job(db)
    run_id = running_run(api, auth, db, job, img)
    left = db.budget_json(job["id"])
    again = confirm(api, auth, job, run_id)
    assert again.status_code == 200 and again.json()["replay"] is True
    assert again.json()["run"]["status"] == "running"
    assert len(adapter.submits) == 1 and db.budget_json(job["id"]) == left


def test_non_owner_confirm_403_without_submit(api, make_token, db, adapter):
    job, img = shop_job(db)
    member = {"Authorization": f"Bearer {make_token(sub=MEMBER)}"}
    run_id = quote(api, member, job, img).json()["run"]["id"]  # 견적은 구성원 가능
    r = confirm(api, member, job, run_id)
    assert r.status_code == 403 and r.json()["code"] == "FORBIDDEN"
    assert adapter.submits == [] and db.gen_runs[0]["status"] == "quoted"


def test_platform_reject_failed_not_billable(api, auth, db, adapter):
    adapter.submit_error = Rejected("http_400")
    job, img = shop_job(db)
    run_id = quote(api, auth, job, img).json()["run"]["id"]
    r = confirm(api, auth, job, run_id)
    assert r.status_code == 502 and r.json()["code"] == "UPSTREAM_ERROR"
    run = db.gen_runs[0]
    assert (
        run["status"] == "failed" and run["billable"] is False and run["error_code"] == "http_400"
    )
    assert db.budget_json(job["id"])["job_left_krw"] == 6_000


@pytest.mark.parametrize("error", [Unknown("timeout"), RuntimeError("boom")])
def test_unknown_submit_keeps_charge_no_resubmit(api, auth, db, adapter, error):
    adapter.submit_error = error
    job, img = shop_job(db)
    run_id = quote(api, auth, job, img).json()["run"]["id"]
    assert confirm(api, auth, job, run_id).status_code == 502
    run = db.gen_runs[0]
    assert run["status"] == "unknown" and run["billable"] is True
    assert db.budget_json(job["id"])["job_left_krw"] == 6_000 - 580
    adapter.submit_error = None
    again = confirm(api, auth, job, run_id)
    assert again.status_code == 200 and again.json()["run"]["status"] == "unknown"
    assert len(adapter.submits) == 1  # 자동 재제출 없음
    assert refresh(api, auth, job, run_id).json()["run"]["status"] == "unknown"
    assert adapter.polls == []


def test_missing_input_photo_not_submitted_not_billable(api, auth, db, adapter):
    job, img = shop_job(db)
    run_id = quote(api, auth, job, img).json()["run"]["id"]
    db.blobs[img["storage_path"]] = b"not-a-jpeg"
    assert confirm(api, auth, job, run_id).status_code == 409
    assert adapter.submits == []
    assert db.gen_runs[0]["status"] == "failed" and db.gen_runs[0]["billable"] is False


def test_two_confirms_only_one_within_budget(api, auth, db, adapter):
    db.cap = 1_000  # 580원 2건 = 1,160원 > 1,000원
    job, img = shop_job(db)
    a = quote(api, auth, job, img, key="g-a").json()["run"]["id"]
    b = quote(api, auth, job, img, key="g-b").json()["run"]["id"]  # 견적 때는 둘 다 통과
    assert confirm(api, auth, job, a).status_code == 202
    r = confirm(api, auth, job, b)
    assert r.status_code == 409 and r.json()["remaining_krw"] == 420
    assert len(adapter.submits) == 1
    assert [r["status"] for r in db.gen_runs] == ["running", "quoted"]


# --- 진행 확인·완료(G1·G5·G6) -----------------------------------------------------------


def test_list_has_no_side_effects(api, auth, db, adapter):
    job, img = shop_job(db)
    running_run(api, auth, db, job, img)
    before = list(db.rpc_calls)
    r = api.get(f"{URL}/{job['id']}/generation-runs", headers=auth)
    assert r.status_code == 200 and len(r.json()["items"]) == 1
    assert "idempotency_key" not in r.json()["items"][0]
    assert adapter.polls == [] and db.rpc_calls == before


def test_refresh_pending_keeps_running(api, auth, db, adapter):
    job, img = shop_job(db)
    run_id = running_run(api, auth, db, job, img)
    r = refresh(api, auth, job, run_id)
    assert r.status_code == 200 and r.json()["run"]["status"] == "running"
    assert adapter.polls == ["req-1"] and "claim" not in db.rpc_calls


def test_refresh_done_saves_source_upload_once(api, auth, db, adapter, mock_supabase):
    mock_supabase.get(RESULT_URL).mock(return_value=httpx.Response(200, content=MP4))
    adapter.poll_result = PollResult("done", video_url=RESULT_URL, cost_usd=Decimal("0.3"))
    job, img = shop_job(db)
    run_id = running_run(api, auth, db, job, img)
    r = refresh(api, auth, job, run_id)
    assert r.status_code == 200, r.text
    run = r.json()["run"]
    assert run["status"] == "done" and run["actual_cost_krw"] == 435  # ceil(0.3*1450)
    asset = next(a for a in db.assets if a["id"] == run["result_asset_id"])
    assert asset["kind"] == "source_upload" and asset["storage_path"] in db.uploads
    assert asset["rights"]["basis"] == "ai_generated" and asset["rights"]["author"] == "운영자"
    assert asset["rights"]["gen"] == {
        "platform": "xai",
        "model": "grok-imagine-video",
        "request_id": "req-1",
        "cost_krw": 435,
    }
    assert asset["reviewed"] is False
    # 중복 refresh: 이미 done → 플랫폼·다운로드·저장 없음
    again = refresh(api, auth, job, run_id)
    assert again.json()["run"]["status"] == "done"
    assert len(db.uploads) == 1 and adapter.polls == ["req-1"]


def test_concurrent_refresh_only_one_finalizes(api, auth, db, adapter, mock_supabase):
    route = mock_supabase.get(RESULT_URL).mock(return_value=httpx.Response(200, content=MP4))
    adapter.poll_result = PollResult("done", video_url=RESULT_URL)
    job, img = shop_job(db)
    run_id = running_run(api, auth, db, job, img)
    db.claim_taken = True  # 다른 refresh가 먼저 running→finalizing을 선점
    r = refresh(api, auth, job, run_id)
    assert r.status_code == 200 and r.json()["run"]["status"] == "running"
    assert (
        not route.called
        and db.uploads == []
        and not any(c.startswith("finish") for c in db.rpc_calls)
    )


def test_platform_failed_keeps_charge(api, auth, db, adapter):
    adapter.poll_result = PollResult("failed", error="platform_failed")
    job, img = shop_job(db)
    run_id = running_run(api, auth, db, job, img)
    r = refresh(api, auth, job, run_id)
    assert r.json()["run"]["status"] == "failed" and r.json()["run"]["billable"] is True


def test_poll_error_502_state_unchanged(api, auth, db, adapter):
    adapter.poll_result = Unknown("http_500")
    job, img = shop_job(db)
    run_id = running_run(api, auth, db, job, img)
    assert refresh(api, auth, job, run_id).status_code == 502
    assert db.gen_runs[0]["status"] == "running"


def test_result_rejected_by_trigger_deletes_object_keeps_charge(
    api, auth, db, adapter, mock_supabase
):
    mock_supabase.get(RESULT_URL).mock(return_value=httpx.Response(200, content=MP4))
    adapter.poll_result = PollResult("done", video_url=RESULT_URL)
    db.reject_result = True
    job, img = shop_job(db)
    run_id = running_run(api, auth, db, job, img)
    r = refresh(api, auth, job, run_id)
    run = r.json()["run"]
    assert run["status"] == "failed" and run["error_code"] == "result_rejected"
    assert run["billable"] is True and db.objects == {}  # 올린 객체 정리


@pytest.mark.parametrize(
    "setup",
    ["redirect_other_host", "private_ip", "other_host", "not_mp4"],
)
def test_download_rejections_fail_run(api, auth, db, adapter, mock_supabase, public_dns, setup):
    url = RESULT_URL
    if setup == "redirect_other_host":
        mock_supabase.get(RESULT_URL).mock(
            return_value=httpx.Response(302, headers={"location": "https://evil.test/x.mp4"})
        )
    elif setup == "private_ip":
        public_dns[:] = ["10.0.0.5"]
    elif setup == "other_host":
        url = "https://evil.test/x.mp4"
    else:
        mock_supabase.get(RESULT_URL).mock(return_value=httpx.Response(200, content=b"<html>"))
    adapter.poll_result = PollResult("done", video_url=url)
    job, img = shop_job(db)
    run_id = running_run(api, auth, db, job, img)
    run = refresh(api, auth, job, run_id).json()["run"]
    assert run["status"] == "failed" and run["error_code"] == "download_rejected"
    assert db.uploads == []


# --- 다운로드 단위(G6) -------------------------------------------------------------------

HOSTS = frozenset({"vidgen.x.ai"})


async def _public(host: str) -> list[str]:
    return [PUBLIC_IP]


@pytest.mark.parametrize(
    "addr", ["127.0.0.1", "10.1.2.3", "192.168.0.1", "169.254.169.254", "::1", "fe80::1", "fc00::1"]
)
@pytest.mark.anyio
async def test_dns_private_addresses_rejected(addr):
    async def res(host: str) -> list[str]:
        return [PUBLIC_IP, addr]

    with pytest.raises(download.DownloadRejected) as e:
        await download.check_dns("vidgen.x.ai", res)
    assert e.value.code == "private_address"


@pytest.mark.parametrize(
    "url",
    [
        "http://vidgen.x.ai/a.mp4",
        "https://user@vidgen.x.ai/a.mp4",
        "https://vidgen.x.ai:8443/a.mp4",
        "https://93.184.216.34/a.mp4",
        "https://evil.test/a.mp4",
        "https://vidgen.x.ai.evil.test/a.mp4",
    ],
)
def test_check_url_rejects(url):
    with pytest.raises(download.DownloadRejected):
        download.check_url(url, HOSTS)


@pytest.mark.anyio
async def test_redirects_allowed_host_max_three():
    with respx.mock(assert_all_called=False) as router:
        for i in range(4):
            router.get(f"https://vidgen.x.ai/r{i}").mock(
                return_value=httpx.Response(302, headers={"location": f"/r{i + 1}"})
            )
        router.get("https://vidgen.x.ai/r4").mock(return_value=httpx.Response(200, content=MP4))
        async with httpx.AsyncClient() as client:
            ok = await download.fetch_video(
                client, "https://vidgen.x.ai/r1", HOSTS, timeout=5, resolver=_public
            )
            assert ok == MP4  # r1→r2→r3→r4: 리다이렉트 3회
            with pytest.raises(download.DownloadRejected) as e:
                await download.fetch_video(
                    client, "https://vidgen.x.ai/r0", HOSTS, timeout=5, resolver=_public
                )
            assert e.value.code == "too_many_redirects"


@pytest.mark.anyio
async def test_byte_cap_streaming():
    with respx.mock() as router:
        router.get(RESULT_URL).mock(return_value=httpx.Response(200, content=MP4 * 4))
        async with httpx.AsyncClient() as client:
            with pytest.raises(download.DownloadRejected) as e:
                await download.fetch_video(
                    client, RESULT_URL, HOSTS, timeout=5, resolver=_public, max_bytes=len(MP4)
                )
    assert e.value.code == "too_large"


# --- 검수(G4) ---------------------------------------------------------------------------


def _done_run(api, auth, db, adapter, mock_supabase) -> tuple[dict, str, str]:
    mock_supabase.get(RESULT_URL).mock(return_value=httpx.Response(200, content=MP4))
    adapter.poll_result = PollResult("done", video_url=RESULT_URL)
    job, img = shop_job(db)
    run_id = running_run(api, auth, db, job, img)
    run = refresh(api, auth, job, run_id).json()["run"]
    return job, run_id, run["result_asset_id"]


def test_review_requires_all_three(api, make_token, db, adapter, mock_supabase, auth):
    job, run_id, asset_id = _done_run(api, auth, db, adapter, mock_supabase)
    member = {"Authorization": f"Bearer {make_token(sub=MEMBER)}"}  # 구성원 검수 가능
    path = f"{URL}/{job['id']}/generation-runs/{run_id}/review"
    r = api.post(path, json={"physics": True, "angle": True, "compare": False}, headers=member)
    assert r.status_code == 200 and r.json()["reviewed"] is False
    assert api.post(path, json={"physics": True, "angle": True}, headers=auth).status_code == 400
    bad = {"physics": "true", "angle": True, "compare": True}
    assert api.post(path, json=bad, headers=auth).status_code == 400
    r = api.post(path, json={"physics": True, "angle": True, "compare": True}, headers=auth)
    assert r.status_code == 200 and r.json()["reviewed"] is True
    asset = next(a for a in db.assets if a["id"] == asset_id)
    assert asset["reviewed"] is True and asset["rights"].get("reviewed") is None


def test_review_not_done_409(api, auth, db, adapter):
    job, img = shop_job(db)
    run_id = running_run(api, auth, db, job, img)
    path = f"{URL}/{job['id']}/generation-runs/{run_id}/review"
    r = api.post(path, json={"physics": True, "angle": True, "compare": True}, headers=auth)
    assert r.status_code == 409


def _gen_rights() -> dict:
    gen = {"platform": "xai", "model": "m", "request_id": "req-1", "cost_krw": 580}
    return {"basis": "ai_generated", "gen": gen}


def test_assets_map_reads_reviewed_column_via_parent():
    up = {
        "id": "u1",
        "kind": "source_upload",
        "status": "ready",
        "rights": {**_gen_rights(), "reviewed": True},  # jsonb 키는 무시
        "reviewed": False,
        "parent_asset_id": None,
    }
    child = {
        "id": "s1",
        "kind": "source",
        "status": "ready",
        "duration_sec": 5,
        "rights": None,
        "reviewed": False,
        "parent_asset_id": "u1",
    }
    assert shopping.assets_map([up, child])["s1"]["reviewed"] is False
    up["reviewed"] = True
    assets = shopping.assets_map([up, child])
    assert assets["s1"]["reviewed"] is True and assets["u1"]["reviewed"] is True


def test_gen_unreviewed_validation_uses_column():
    up = {"id": "u1", "kind": "source_upload", "status": "ready", "rights": _gen_rights()}
    child = {
        "id": "s1",
        "kind": "source",
        "status": "ready",
        "duration_sec": 30,
        "parent_asset_id": "u1",
    }
    spec = vs.good()
    for cut in spec["cuts"]:
        if cut["source_asset_id"] == "a1":
            cut["source_asset_id"] = "s1"

    def codes(reviewed: bool) -> list[str]:
        assets = {**vs._assets(), **shopping.assets_map([{**up, "reviewed": reviewed}, child])}
        return [e["code"] for e in validate_shopping_spec(spec, assets=assets)["errors"]]

    assert codes(False) == ["gen.unreviewed"]
    assert codes(True) == []


# --- xAI 어댑터(respx 모의, 실제 호출 없음) -------------------------------------------------


def _xai(client: httpx.AsyncClient) -> XaiAdapter:
    return XaiAdapter(client, SecretStr(XAI_KEY), 5)


@pytest.mark.anyio
async def test_xai_submit_ok_body_base64_key_header_only():
    with respx.mock() as router:
        route = router.post(f"{API_BASE}/videos/generations").mock(
            return_value=httpx.Response(200, json={"request_id": "abc_1"})
        )
        async with httpx.AsyncClient() as client:
            assert await _xai(client).submit(JPEG, "image/jpeg", "p", 5) == "abc_1"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["image"]["url"] == "data:image/jpeg;base64," + base64.b64encode(JPEG).decode()
    assert req.headers["authorization"] == f"Bearer {XAI_KEY}"
    assert XAI_KEY not in req.content.decode()


@pytest.mark.parametrize(
    "resp,exc,code",
    [
        (httpx.Response(400, json={"error": "bad"}), Rejected, "http_400"),
        (httpx.Response(429), Rejected, "http_429"),
        (httpx.Response(408), Unknown, "http_408"),
        (httpx.Response(500), Unknown, "http_500"),
        (httpx.Response(200, json={"request_id": "../x"}), Unknown, "bad_response"),
        (httpx.TimeoutException("t"), Unknown, "timeout"),
    ],
)
@pytest.mark.anyio
async def test_xai_submit_classification(resp, exc, code):
    with respx.mock() as router:
        route = router.post(f"{API_BASE}/videos/generations")
        if isinstance(resp, Exception):
            route.mock(side_effect=resp)
        else:
            route.mock(return_value=resp)
        async with httpx.AsyncClient() as client:
            with pytest.raises(exc) as e:
                await _xai(client).submit(JPEG, "image/jpeg", "p", 5)
    assert e.value.code == code


@pytest.mark.anyio
async def test_xai_poll_states():
    with respx.mock() as router:
        route = router.get(f"{API_BASE}/videos/abc_1")
        async with httpx.AsyncClient() as client:
            a = _xai(client)
            route.mock(return_value=httpx.Response(200, json={"status": "pending"}))
            assert (await a.poll("abc_1")).status == "pending"
            route.mock(
                return_value=httpx.Response(
                    200, json={"status": "done", "video": {"url": RESULT_URL}, "cost_usd": 0.4}
                )
            )
            done = await a.poll("abc_1")
            assert done.video_url == RESULT_URL and done.cost_usd == Decimal("0.4")
            route.mock(return_value=httpx.Response(200, json={"status": "expired"}))
            assert (await a.poll("abc_1")).status == "failed"
            with pytest.raises(Unknown):
                await a.poll("../etc")


# --- 리뷰 반영 ----------------------------------------------------------------------------


def test_mark_failure_retried_once(api, auth, db, adapter):
    db.mark_failures = 1
    job, img = shop_job(db)
    run_id = quote(api, auth, job, img).json()["run"]["id"]
    r = confirm(api, auth, job, run_id)
    assert r.status_code == 202 and r.json()["run"]["status"] == "running"
    assert db.rpc_calls.count("mark:running") == 2


def test_mark_failure_twice_logs_hash_then_stalled_unknown(api, auth, db, adapter, caplog):
    db.mark_failures = 2
    job, img = shop_job(db)
    run_id = quote(api, auth, job, img).json()["run"]["id"]
    assert confirm(api, auth, job, run_id).status_code == 503
    run = db.gen_runs[0]
    assert run["status"] == "confirmed" and run["billable"] is True
    assert "request_sha256=" in caplog.text and "req-1" not in caplog.text
    # 5분 안: 재확인은 현재 run(재제출 없음)
    assert confirm(api, auth, job, run_id).json()["run"]["status"] == "confirmed"
    run["confirmed_at"] = (datetime.now(UTC) - timedelta(minutes=6)).isoformat()
    again = confirm(api, auth, job, run_id)
    assert again.status_code == 200 and again.json()["run"]["status"] == "unknown"
    assert again.json()["run"]["error_code"] == "submit_stalled" and run["billable"] is True
    assert len(adapter.submits) == 1


def test_refresh_closes_stalled_confirmed(api, auth, db, adapter):
    db.mark_failures = 2
    job, img = shop_job(db)
    run_id = quote(api, auth, job, img).json()["run"]["id"]
    confirm(api, auth, job, run_id)
    db.gen_runs[0]["confirmed_at"] = (datetime.now(UTC) - timedelta(minutes=6)).isoformat()
    assert refresh(api, auth, job, run_id).json()["run"]["status"] == "unknown"
    assert adapter.polls == []


def test_finish_lost_response_keeps_object_when_saved(api, auth, db, adapter, mock_supabase):
    mock_supabase.get(RESULT_URL).mock(return_value=httpx.Response(200, content=MP4))
    adapter.poll_result = PollResult("done", video_url=RESULT_URL)
    db.finish_lost_response = True
    job, img = shop_job(db)
    run_id = running_run(api, auth, db, job, img)
    assert refresh(api, auth, job, run_id).status_code == 503
    run = db.gen_runs[0]
    assert run["status"] == "done" and len(db.objects) == 1  # 저장된 자산의 객체는 유지


def test_finish_error_deletes_object_when_not_saved(api, auth, db, adapter, mock_supabase):
    mock_supabase.get(RESULT_URL).mock(return_value=httpx.Response(200, content=MP4))
    adapter.poll_result = PollResult("done", video_url=RESULT_URL)
    job, img = shop_job(db)
    run_id = running_run(api, auth, db, job, img)
    db.fail_rpc = "finish_generation_run"
    assert refresh(api, auth, job, run_id).status_code == 503
    assert db.gen_runs[0]["status"] == "finalizing" and db.objects == {}


def test_stale_claimer_cannot_overwrite(api, auth, db, adapter, mock_supabase):
    """회수 뒤 다른 요청이 새 토큰으로 선점하면 이전 선점자의 완료 기록은 거부된다."""
    adapter.poll_result = PollResult("failed", error="platform_failed")
    job, img = shop_job(db)
    run_id = running_run(api, auth, db, job, img)
    real_claim = db.claim

    def claim_then_reclaimed(body: dict) -> httpx.Response:
        resp = real_claim(body)
        db.gen_runs[0]["finalize_token"] = str(uuid.uuid4())  # 다른 요청이 회수·재선점
        return resp

    db.claim = claim_then_reclaimed  # type: ignore[method-assign]
    assert refresh(api, auth, job, run_id).status_code == 409
    assert db.gen_runs[0]["status"] == "finalizing"


@pytest.mark.parametrize(
    "cost,expected",
    [(Decimal("0.3"), 435), (Decimal("100"), None), (Decimal("1e12"), None)],
)
def test_reported_cost_capped(api, auth, db, adapter, mock_supabase, cost, expected):
    mock_supabase.get(RESULT_URL).mock(return_value=httpx.Response(200, content=MP4))
    adapter.poll_result = PollResult("done", video_url=RESULT_URL, cost_usd=cost)
    job, img = shop_job(db)
    run_id = running_run(api, auth, db, job, img)
    run = refresh(api, auth, job, run_id).json()["run"]
    assert run["status"] == "done" and run["actual_cost_krw"] == expected
    asset = next(a for a in db.assets if a["id"] == run["result_asset_id"])
    assert asset["rights"]["gen"]["cost_krw"] == (expected or 580)
