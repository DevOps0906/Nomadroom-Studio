"""A-07 POST /v1/verify-runs 단위 테스트(PostgREST·YouTube 모두 목)."""

import asyncio
import io
import logging
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from app.logging_mask import mask, setup_logging
from tests.youtube.conftest import (
    BROADCASTER,
    CHANNEL_X,
    PROFILE_JP,
    PROFILE_KR,
    YT_KEY,
    FakeDB,
    cand_id,
    target,
    video_id,
    yt_item,
)

URL = "/v1/verify-runs"


def ago(**kw) -> datetime:
    return datetime.now(UTC) - timedelta(**kw)


def seed_three(db: FakeDB) -> None:
    """1: 이전 관측 2일 전(1000) → 1005, 2: 관측 없음·방송사 채널, 3: YouTube 응답에서 빠짐."""
    db.targets = [target(2), target(1, ago(days=2)), target(3, ago(days=3))]
    db.observations = [
        {
            "id": "00000000-0000-4000-8000-00000000e001",
            "candidate_id": cand_id(1),
            "observed_at": ago(days=2).isoformat(),
            "view_count": 1000,
        }
    ]
    db.youtube = {
        video_id(1): yt_item(video_id(1), 1005),
        video_id(2): yt_item(video_id(2), 50, license="youtube", channel=BROADCASTER),
    }
    db.skipped = 7


@pytest.fixture
def log_stream():
    stream = io.StringIO()
    handler = setup_logging(stream=stream)
    try:
        yield stream
    finally:
        logging.getLogger().removeHandler(handler)


# --- 정상 흐름 -----------------------------------------------------------------


def test_verify_run_success(api: TestClient, db: FakeDB, headers):
    seed_three(db)
    resp = api.post(URL, headers=headers)
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["job"]["kind"] == "verify" and body["job"]["status"] == "done"
    assert (body["checked"], body["skipped_recent"], body["failed"]) == (2, 7, 1)
    assert body["counts"] == {
        "total": 10,
        "producible": 1,
        "pending": 2,
        "excluded": 3,
        "used": 4,
    }

    job = db.jobs[0]
    assert job["status"] == "done" and job["error"] is None and job["result"]["checked"] == 2
    assert job["profile_ids"] == [PROFILE_KR, PROFILE_JP]

    # videos.list 1회, 키는 헤더로만
    assert len(db.youtube_calls) == 1
    call = db.youtube_calls[0]
    assert call.headers["X-Goog-Api-Key"] == YT_KEY
    assert YT_KEY not in str(call.url) and "key=" not in str(call.url)
    assert "part=snippet%2Cstatistics%2Cstatus" in str(call.url)
    assert db.quota_units == 1

    items = {i["candidate_id"]: i for i in db.applied[0]["p_payload"]["items"]}
    assert set(items) == {cand_id(1), cand_id(2)}
    one = items[cand_id(1)]
    assert one["view_count"] == 1005 and one["license_cc"] is True
    assert one["channel_id"] == CHANNEL_X and one["is_broadcaster"] is False
    kr = next(v for v in one["verdicts"] if v["profile_id"] == PROFILE_KR)
    assert kr == {
        "profile_id": PROFILE_KR,
        "status": "producible",
        "reason": None,
        "growth_pct": "0.50",
        "prev_observation_id": "00000000-0000-4000-8000-00000000e001",
    }
    jp = next(v for v in one["verdicts"] if v["profile_id"] == PROFILE_JP)
    assert jp["status"] == "excluded" and jp["reason"] == "market"
    assert one["rep_status"] == "producible" and one["rep_profile_id"] == PROFILE_KR

    two = items[cand_id(2)]
    assert two["license_cc"] is False and two["is_broadcaster"] is True
    kr2 = next(v for v in two["verdicts"] if v["profile_id"] == PROFILE_KR)
    assert kr2["status"] == "pending" and kr2["reason"] == "no_prev"
    assert two["rep_status"] == "pending" and two["rep_profile_id"] == PROFILE_KR


def test_representative_uses_existing_verdicts_by_name_order(api: TestClient, db: FakeDB, headers):
    """profile_ids로 일본만 검증해도, 기존 한국 판정(producible)이 대표가 된다."""
    db.targets = [target(1, ago(days=2), market="JP")]
    db.youtube = {video_id(1): yt_item(video_id(1), 10)}
    db.verdicts = [{"candidate_id": cand_id(1), "profile_id": PROFILE_KR, "status": "producible"}]
    resp = api.post(URL, headers=headers, json={"profile_ids": [PROFILE_JP]})
    assert resp.status_code == 200, resp.json()
    item = db.applied[0]["p_payload"]["items"][0]
    assert [v["profile_id"] for v in item["verdicts"]] == [PROFILE_JP]
    assert item["rep_status"] == "producible" and item["rep_profile_id"] == PROFILE_KR


def test_skipped_recent_and_no_targets(api: TestClient, db: FakeDB, headers):
    db.skipped = 3
    resp = api.post(URL, headers=headers)
    assert resp.status_code == 200
    assert (resp.json()["checked"], resp.json()["skipped_recent"]) == (0, 3)
    assert db.youtube_calls == [] and db.quota_units == 0


def test_invalid_video_id_counts_failed_without_call(api: TestClient, db: FakeDB, headers):
    db.targets = [target(1, video_id="bad id/../")]
    resp = api.post(URL, headers=headers)
    assert resp.status_code == 200 and resp.json()["failed"] == 1
    assert db.youtube_calls == []


def test_500_candidates_capped_to_200_and_4_calls(api: TestClient, db: FakeDB, headers):
    db.targets = [target(n) for n in range(1, 501)]
    db.youtube = {video_id(n): yt_item(video_id(n), 100) for n in range(1, 501)}
    resp = api.post(URL, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["checked"] == 200
    assert len(db.youtube_calls) <= 4 and db.quota_units == len(db.youtube_calls)
    for call in db.youtube_calls:
        assert len(call.url.params["id"].split(",")) <= 50


def test_failed_batch_keeps_others(api: TestClient, db: FakeDB, headers):
    db.targets = [target(n) for n in range(1, 101)]
    db.youtube = {video_id(n): yt_item(video_id(n), 100) for n in range(1, 101)}
    db.fail_apply_calls = {1}
    resp = api.post(URL, headers=headers)
    assert resp.status_code == 200
    assert (resp.json()["checked"], resp.json()["failed"]) == (50, 50)


# --- 멱등·동시 실행 -------------------------------------------------------------


def test_same_key_returns_same_job(api: TestClient, db: FakeDB, headers):
    seed_three(db)
    first = api.post(URL, headers=headers)
    second = api.post(URL, headers=headers, json={"profile_ids": [PROFILE_JP]})
    assert second.status_code == 200
    assert second.json() == first.json()
    assert len(db.jobs) == 1 and len(db.youtube_calls) == 1


def test_same_key_running_returns_status_only(api: TestClient, db: FakeDB, headers):
    db.jobs = [
        {
            "id": str(uuid.uuid4()),
            "kind": "verify",
            "status": "running",
            "idempotency_key": "run-1",
            "result": None,
            "started_at": datetime.now(UTC).isoformat(),
        }
    ]
    resp = api.post(URL, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["job"]["status"] == "running" and body["checked"] is None
    assert body["counts"] is None


def test_same_key_other_kind_409(api: TestClient, db: FakeDB, headers):
    db.jobs = [
        {
            "id": str(uuid.uuid4()),
            "kind": "collect",
            "status": "done",
            "idempotency_key": "run-1",
            "result": None,
        }
    ]
    resp = api.post(URL, headers=headers)
    assert resp.status_code == 409 and resp.json()["code"] == "CONFLICT"
    assert len(db.jobs) == 1


def test_active_job_409(api: TestClient, db: FakeDB, headers):
    db.jobs = [
        {
            "id": str(uuid.uuid4()),
            "kind": "verify",
            "status": "running",
            "idempotency_key": "other",
            "result": None,
            "started_at": ago(minutes=2).isoformat(),
        }
    ]
    resp = api.post(URL, headers=headers)
    assert resp.status_code == 409
    assert resp.json() == {"code": "CONFLICT", "message": "검증이 이미 진행 중입니다."}


def test_stale_running_job_is_expired(api: TestClient, db: FakeDB, headers):
    stale = {
        "id": str(uuid.uuid4()),
        "kind": "verify",
        "status": "running",
        "idempotency_key": "old",
        "result": None,
        "started_at": ago(minutes=11).isoformat(),
    }
    db.jobs = [stale]
    resp = api.post(URL, headers=headers)
    assert resp.status_code == 200
    assert stale["status"] == "failed" and stale["error"] == "timeout"
    assert len(db.jobs) == 2


def test_concurrent_same_key_insert_returns_existing(api: TestClient, db: FakeDB, headers):
    """조회 뒤 다른 요청이 먼저 넣은 경우: 23505(멱등 키 제약) → 기존 job 반환."""
    existing = {
        "id": str(uuid.uuid4()),
        "kind": "verify",
        "status": "running",
        "idempotency_key": "run-1",
        "result": None,
        "started_at": datetime.now(UTC).isoformat(),
    }
    calls = {"n": 0}
    original = db.jobs

    class Late(list):
        def __iter__(self):
            calls["n"] += 1
            # 첫 조회(GET)에는 비어 있고, 이후에는 기존 job이 보인다
            return iter([] if calls["n"] == 1 else [existing])

    db.jobs = Late(original)
    db.job_insert_conflict = "jobs_workspace_id_idempotency_key_key"
    resp = api.post(URL, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["job"] == {"id": existing["id"], "kind": "verify", "status": "running"}


# --- 할당량 방어선 ---------------------------------------------------------------


def test_quota_limit_429_keeps_previous_verdicts(api: TestClient, db: FakeDB, headers):
    seed_three(db)
    db.quota_units = 8_000
    resp = api.post(URL, headers=headers)
    assert resp.status_code == 429
    assert resp.json()["code"] == "QUOTA_EXCEEDED"
    assert db.youtube_calls == [] and db.applied == []  # 판정 변경 없음
    assert db.jobs[0]["status"] == "failed" and db.jobs[0]["error"] == "quota_exceeded"


def test_quota_runs_out_mid_run(api: TestClient, db: FakeDB, headers):
    db.targets = [target(n) for n in range(1, 101)]
    db.youtube = {video_id(n): yt_item(video_id(n), 100) for n in range(1, 101)}
    db.quota_units = 7_999
    resp = api.post(URL, headers=headers)
    assert resp.status_code == 429
    assert len(db.applied) == 1 and len(db.youtube_calls) == 1  # 첫 묶음만 반영
    assert db.jobs[0]["result"]["checked"] == 50


def test_youtube_403_quota_exceeded_is_429(api: TestClient, db: FakeDB, headers):
    seed_three(db)
    db.youtube_error = httpx.Response(
        403,
        json={
            "error": {
                "code": 403,
                "message": "The request cannot be completed because you have exceeded your quota.",
                "errors": [{"domain": "youtube.quota", "reason": "quotaExceeded"}],
            }
        },
    )
    resp = api.post(URL, headers=headers)
    assert resp.status_code == 429 and resp.json()["code"] == "QUOTA_EXCEEDED"
    assert db.applied == []


def test_youtube_other_403_is_502(api: TestClient, db: FakeDB, headers):
    seed_three(db)
    db.youtube_error = httpx.Response(
        403, json={"error": {"code": 403, "errors": [{"reason": "forbidden"}]}}
    )
    resp = api.post(URL, headers=headers)
    assert resp.status_code == 502 and resp.json()["code"] == "UPSTREAM_ERROR"
    assert db.jobs[0]["error"] == "upstream_error"


# --- 입력 검증 -----------------------------------------------------------------


def test_missing_idempotency_key_400(api: TestClient, headers):
    h = {"Authorization": headers["Authorization"]}
    resp = api.post(URL, headers=h)
    assert resp.status_code == 400 and resp.json()["field"] == "Idempotency-Key"


def test_unknown_profile_400(api: TestClient, db: FakeDB, headers):
    resp = api.post(URL, headers=headers, json={"profile_ids": [str(uuid.uuid4())]})
    assert resp.status_code == 400 and resp.json()["field"] == "profile_ids"
    assert db.jobs == []


def test_no_selected_profile_400(api: TestClient, db: FakeDB, headers):
    for p in db.profiles:
        p["selected"] = False
    resp = api.post(URL, headers=headers)
    assert resp.status_code == 400


def test_more_than_three_profiles_400(api: TestClient, headers):
    ids = [str(uuid.uuid4()) for _ in range(4)]
    assert api.post(URL, headers=headers, json={"profile_ids": ids}).status_code == 400


def test_unauthenticated_401(api: TestClient):
    assert api.post(URL, headers={"Idempotency-Key": "k"}).status_code == 401


# --- 키 노출 -------------------------------------------------------------------


def test_youtube_500_logs_have_no_key(api: TestClient, db: FakeDB, headers, log_stream):
    seed_three(db)
    db.youtube_error = httpx.Response(500, text=f"echo key={YT_KEY}")
    resp = api.post(URL, headers=headers)
    assert resp.status_code == 502
    out = log_stream.getvalue()
    assert "HTTPStatusError" in out  # 실제 예외 경로(exc_info)가 기록됐다
    assert YT_KEY not in out and YT_KEY not in resp.text


def test_unhandled_exception_logs_have_no_key(api: TestClient, db: FakeDB, headers, log_stream):
    """errors.py 처리되지 않은 예외(exc_info) 경로에서 키가 섞인 메시지도 마스킹된다."""
    seed_three(db)
    db.youtube_error = RuntimeError(f"GET https://x/videos?key={YT_KEY} X-Goog-Api-Key: {YT_KEY}")
    resp = api.post(URL, headers=headers)
    assert resp.status_code == 500 and resp.json()["code"] == "INTERNAL"
    out = log_stream.getvalue()
    assert "처리되지 않은 예외" in out and "RuntimeError" in out
    assert YT_KEY not in out and YT_KEY not in resp.text
    assert db.jobs[0]["status"] == "failed" and db.jobs[0]["error"] == "internal"


def test_missing_api_key_502(mock_supabase, jwks_payload, db: FakeDB, headers):
    from app.main import create_app
    from tests.conftest import JWKS_URL, WORKSPACE_ID, make_settings
    from tests.youtube.conftest import REST, install

    mock_supabase.get(JWKS_URL).mock(return_value=httpx.Response(200, json=jwks_payload))
    mock_supabase.get(f"{REST}/workspace_members").mock(
        return_value=httpx.Response(200, json=[{"workspace_id": str(WORKSPACE_ID)}])
    )
    install(mock_supabase, db)
    with TestClient(create_app(make_settings()), raise_server_exceptions=False) as c:
        resp = c.post(URL, headers=headers)
    assert resp.status_code == 502 and db.jobs == []


def test_mask_google_key_patterns():
    assert mask(f"k {YT_KEY} end") == "k *** end"
    assert mask(f"https://x/v?id=1&key={YT_KEY}") == "https://x/v?id=1&key=***"


# --- 리뷰 반영(task-006 리뷰 반영 결정) ----------------------------------------


def _obs(n: int, cand: int, when: datetime, views: int) -> dict:
    return {
        "id": f"00000000-0000-4000-8000-00000000e{n:03d}",
        "candidate_id": cand_id(cand),
        "observed_at": when.isoformat(),
        "view_count": views,
    }


def test_prev_is_latest_observation_in_valid_interval(api: TestClient, db: FakeDB, headers):
    """관측 1·3·8일 전 → prev는 1일 전. 2시간·3일 전 → 24시간 미만은 건너뛰고 3일 전."""
    db.targets = [target(1, ago(days=1)), target(2, ago(hours=2))]
    db.observations = [
        _obs(3, 1, ago(days=3), 900),
        _obs(8, 1, ago(days=8), 800),
        _obs(1, 1, ago(days=1), 1000),
        _obs(22, 2, ago(days=3), 1000),
        _obs(21, 2, ago(hours=2), 1004),
    ]
    db.youtube = {video_id(n): yt_item(video_id(n), 1005) for n in (1, 2)}
    resp = api.post(URL, headers=headers)
    assert resp.status_code == 200, resp.json()
    assert db.observation_params[0]["order"] == "candidate_id.asc,observed_at.desc"
    items = {i["candidate_id"]: i for i in db.applied[0]["p_payload"]["items"]}
    kr1 = next(v for v in items[cand_id(1)]["verdicts"] if v["profile_id"] == PROFILE_KR)
    assert kr1["prev_observation_id"] == _obs(1, 1, ago(days=1), 0)["id"]
    kr2 = next(v for v in items[cand_id(2)]["verdicts"] if v["profile_id"] == PROFILE_KR)
    assert kr2["prev_observation_id"] == _obs(22, 2, ago(days=3), 0)["id"]


def _job(key: str, created: datetime, status: str = "done") -> dict:
    return {
        "id": str(uuid.uuid4()),
        "kind": "verify",
        "status": status,
        "idempotency_key": key,
        "result": None,
        "created_at": created.isoformat(),
        "started_at": created.isoformat(),
    }


def test_new_key_within_60s_is_rate_limited(api: TestClient, db: FakeDB, headers):
    db.jobs = [_job("prev", ago(seconds=30))]
    resp = api.post(URL, headers=headers)
    assert resp.status_code == 429 and resp.json()["code"] == "RATE_LIMITED"
    assert len(db.jobs) == 1 and db.youtube_calls == [] and db.quota_units == 0


def test_new_key_after_60s_is_allowed(api: TestClient, db: FakeDB, headers):
    db.jobs = [_job("prev", ago(seconds=61))]
    assert api.post(URL, headers=headers).status_code == 200
    assert len(db.jobs) == 2


def test_same_key_within_60s_returns_existing_job(api: TestClient, db: FakeDB, headers):
    db.jobs = [_job("run-1", ago(seconds=5))]
    resp = api.post(URL, headers=headers)
    assert resp.status_code == 200 and resp.json()["job"]["id"] == db.jobs[0]["id"]


def test_youtube_values_are_bounded(api: TestClient, db: FakeDB, headers):
    db.targets = [target(n) for n in range(1, 7)]
    db.youtube = {
        video_id(1): yt_item(video_id(1), 10),
        video_id(2): yt_item(video_id(2), 10, channel="UCshort"),
        video_id(3): yt_item(video_id(3), 10),
        video_id(4): yt_item(video_id(4), 10),
        video_id(5): yt_item(video_id(5), 10),
        video_id(6): yt_item(video_id(6), 10, channel=BROADCASTER + "x"),
    }
    db.youtube[video_id(1)]["snippet"].update({"channelTitle": "가" * 250, "title": "나" * 400})
    db.youtube[video_id(3)]["statistics"]["viewCount"] = "1" * 19  # bigint 초과 위험
    db.youtube[video_id(4)]["statistics"]["viewCount"] = "١٢٣"  # 비 ASCII 숫자
    db.youtube[video_id(5)]["statistics"]["viewCount"] = "-5"
    resp = api.post(URL, headers=headers)
    assert resp.status_code == 200, resp.json()
    assert (resp.json()["checked"], resp.json()["failed"]) == (3, 3)
    items = {i["candidate_id"]: i for i in db.applied[0]["p_payload"]["items"]}
    assert set(items) == {cand_id(1), cand_id(2), cand_id(6)}
    assert items[cand_id(1)]["channel_title"] == "가" * 200
    assert items[cand_id(2)]["channel_id"] is None
    assert items[cand_id(6)]["channel_id"] is None and items[cand_id(6)]["is_broadcaster"] is False


def test_parse_item_limits_title_and_accepts_18_digit_views():
    from app.youtube.client import _parse_item

    item = yt_item(video_id(1), 10)
    item["snippet"]["title"] = "제" * 301
    item["statistics"]["viewCount"] = "9" * 18
    info = _parse_item(item)
    assert info is not None and info.title == "제" * 300 and info.view_count == int("9" * 18)
    assert info.channel_id == CHANNEL_X


def test_finished_job_rejects_batch(api: TestClient, db: FakeDB, headers):
    """실행 중 job이 정리(failed)되면 RPC가 거부 → 그 묶음은 failed, 반영 없음."""
    seed_three(db)

    def expire() -> None:
        db.jobs[0]["status"] = "failed"

    db.on_youtube = expire
    resp = api.post(URL, headers=headers)
    assert resp.status_code == 200
    assert (resp.json()["checked"], resp.json()["failed"]) == (0, 3)
    assert db.applied == []


def test_batch_context_failure_fails_only_that_batch(api: TestClient, db: FakeDB, headers):
    db.targets = [target(n) for n in range(1, 101)]
    db.youtube = {video_id(n): yt_item(video_id(n), 100) for n in range(1, 101)}
    db.fail_observation_calls = {1}
    resp = api.post(URL, headers=headers)
    assert resp.status_code == 200, resp.json()
    assert (resp.json()["checked"], resp.json()["failed"]) == (50, 50)
    assert db.apply_calls == 1


def test_finish_patch_retried_once(api: TestClient, db: FakeDB, headers):
    seed_three(db)
    db.finish_failures = 1
    resp = api.post(URL, headers=headers)
    assert resp.status_code == 200
    assert db.jobs[0]["status"] == "done"


def test_finish_patch_fails_twice_is_error(api: TestClient, db: FakeDB, headers):
    seed_three(db)
    db.finish_failures = 2
    resp = api.post(URL, headers=headers)
    assert resp.status_code >= 500
    assert db.jobs[0]["status"] == "running"  # 10분 뒤 정리 대상


def test_cancelled_closes_job_and_reraises(api: TestClient, db: FakeDB, headers):
    """취소(CancelledError, BaseException)도 job을 failed로 닫고 다시 올린다."""
    seed_three(db)

    def cancel() -> None:
        task = asyncio.current_task()
        assert task is not None
        task.cancel()

    db.on_youtube = cancel
    api.post(URL, headers=headers)  # 취소는 서버 밖으로 올라간다(TestClient는 500으로 보인다)
    assert db.jobs[0]["status"] == "failed" and db.jobs[0]["error"] == "internal"


def test_youtube_api_key_format_validated():
    from pydantic import ValidationError

    from tests.conftest import make_settings

    bad = "AIza-too-short-secret"
    with pytest.raises(ValidationError) as exc:
        make_settings(youtube_api_key=bad)
    assert bad not in str(exc.value)
    assert make_settings(youtube_api_key="").youtube_api_key is None
    assert make_settings(youtube_api_key=YT_KEY).youtube_api_key is not None
