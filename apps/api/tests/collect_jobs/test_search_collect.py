"""task-019 YouTube 검색 후보 수집(가짜 PostgREST + YouTube 목). 근거: task-019.md#착수 결정."""

import logging
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from app.collect.search import measured_format, search_params
from app.routes.verify_runs import _profile
from app.youtube.client import parse_duration
from tests.collect_jobs.conftest import (
    JOB,
    P1,
    P2,
    SEARCH,
    YT_KEY,
    FakeDB,
    job,
    profile,
    run,
    yt_video,
)


def vid(n: int) -> str:
    return f"srch{n:07d}"  # 11자


def _post(api: TestClient, auth: dict, key: str = "s-1", body: dict | None = None):
    return api.post("/v1/collect-jobs", headers={**auth, "Idempotency-Key": key}, json=body)


def _only(db: FakeDB, *pids: str) -> None:
    for p in db.profiles:
        p["selected"] = p["id"] in pids


def _quota_403() -> httpx.Response:
    return httpx.Response(403, json={"error": {"errors": [{"reason": "quotaExceeded"}]}})


# --- 파라미터 매핑 -----------------------------------------------------------------


def test_search_params_kr_all_no_keywords():
    p = _profile(profile(P1, "가"))
    assert search_params(p) == {
        "part": "id",
        "type": "video",
        "maxResults": 50,
        "order": "viewCount",
        "regionCode": "KR",
        "relevanceLanguage": "ko",
    }


def test_search_params_jp_short_keywords_or():
    p = _profile(profile(P1, "가", market="JP", format="short", keywords=["猫", "犬 動画"]))
    params = search_params(p)
    assert params["regionCode"] == "JP" and params["relevanceLanguage"] == "ja"
    assert params["q"] == "猫 | 犬 動画"
    assert params["videoDuration"] == "short"
    assert "publishedAfter" not in params


def test_search_params_long_no_duration_filter():
    params = search_params(_profile(profile(P1, "가", format="long")))
    assert "videoDuration" not in params and "q" not in params


def test_post_sends_mapped_params_and_key_header_only(
    api: TestClient, auth: dict, db: FakeDB, mock_supabase
):
    _only(db, P1)
    db.profiles[0].update(keywords=["a", "b"], format="short")
    assert _post(api, auth).status_code == 202
    assert db.search_calls == [
        {
            "part": "id",
            "type": "video",
            "maxResults": "50",
            "order": "viewCount",
            "regionCode": "KR",
            "relevanceLanguage": "ko",
            "q": "a | b",
            "videoDuration": "short",
        }
    ]
    for call in mock_supabase.calls:
        if "googleapis" in str(call.request.url):
            assert YT_KEY not in str(call.request.url)
            assert call.request.headers["x-goog-api-key"] == YT_KEY


# --- 형식 실측 ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "seconds"),
    [("PT2M59S", 179), ("PT3M", 180), ("PT3M1S", 181), ("P1DT1S", 86401), ("P0D", None)],
)
def test_parse_duration(raw: str, seconds: int | None):
    assert parse_duration(raw) == seconds


@pytest.mark.parametrize("raw", ["", "P", "PT", "1M", "PT1.5S", None, 30])
def test_parse_duration_invalid(raw):
    assert parse_duration(raw) is None


def test_measured_format_boundary():
    assert measured_format(180) == "short"
    assert measured_format(181) == "long"
    assert measured_format(None) is None


def test_shorts_profile_excludes_measured_long(api: TestClient, auth: dict, db: FakeDB):
    _only(db, P1)
    db.profiles[0]["format"] = "short"
    db.search_results = [[vid(1), vid(2)]]
    db.videos = {
        vid(1): yt_video(vid(1), duration="PT3M"),
        vid(2): yt_video(vid(2), duration="PT3M1S"),
    }
    resp = _post(api, auth)
    assert resp.json()["job"]["status"] == "done"
    by_vid = {c["video_id"]: c for c in db.candidates}
    assert by_vid[vid(1)]["format"] == "short" and by_vid[vid(2)]["format"] == "long"
    v = {(x["candidate_id"], x["profile_id"]): x for x in db.verdicts}
    assert v[(by_vid[vid(1)]["id"], P1)]["reason"] == "no_prev"
    assert v[(by_vid[vid(2)]["id"], P1)]["reason"] == "format"
    assert db.video_calls[0]["part"] == "snippet,statistics,status,contentDetails"


# --- 할당량 ------------------------------------------------------------------------


def test_search_daily_limit_429_no_job(api: TestClient, auth: dict, db: FakeDB):
    db.search_units = 1_901  # 2프로필 × 100 = 200 → 2,101 > 2,000
    db.quota_units = 1_901
    resp = _post(api, auth)
    assert resp.status_code == 429 and resp.json()["code"] == "QUOTA_EXCEEDED"
    assert db.jobs == [] and db.runs == [] and db.search_calls == []
    assert (db.search_units, db.quota_units) == (1_901, 1_901)  # 변경 없음


def test_search_limit_boundary_exact_ok(api: TestClient, auth: dict, db: FakeDB):
    db.search_units = 1_800
    db.quota_units = 1_800
    assert _post(api, auth).status_code == 202
    assert db.search_units == 2_000


def test_total_defense_line_429_no_job(api: TestClient, auth: dict, db: FakeDB):
    db.quota_units = 7_950  # 검색 상한은 여유, 전체 방어선 8,000 초과
    resp = _post(api, auth)
    assert resp.status_code == 429 and resp.json()["code"] == "QUOTA_EXCEEDED"
    assert db.jobs == [] and db.search_units == 0 and db.quota_units == 7_950


def test_reservation_is_profiles_times_100(api: TestClient, auth: dict, db: FakeDB):
    _post(api, auth)
    reserve = [b for name, b in db.rpc_calls if name == "reserve_search"]
    assert reserve == [{"p_units": 200, "p_search_limit": 2_000, "p_limit": 8_000}]


def test_active_job_409_before_reserving(api: TestClient, auth: dict, db: FakeDB):
    db.jobs.append(job(status="queued"))
    assert _post(api, auth, key="new").status_code == 409
    assert db.search_units == 0


def test_videos_quota_denied_fails_job(api: TestClient, auth: dict, db: FakeDB):
    _only(db, P1)
    db.quota_units = 7_900  # 검색 100 예약 후 8,000 → videos.list 1 unit 예약 실패
    db.search_results = [[vid(1)]]
    db.videos = {vid(1): yt_video(vid(1))}
    out = _post(api, auth).json()["job"]
    assert out["status"] == "failed" and out["error"] == "quota_exceeded"
    assert db.video_calls == [] and db.candidates == []


def test_youtube_403_quota_fails_job(api: TestClient, auth: dict, db: FakeDB):
    db.search_error = _quota_403()
    out = _post(api, auth).json()["job"]
    assert out["status"] == "failed" and out["error"] == "quota_exceeded"


# --- 결과 반영 ---------------------------------------------------------------------


def test_duplicates_and_missing_excluded(api: TestClient, auth: dict, db: FakeDB):
    _only(db, P1)
    db.candidates.append(
        {
            "id": "c-old",
            "workspace_id": db.profiles[0]["workspace_id"],
            "video_id": vid(1),
            "first_job_id": None,
            "used": False,
        }
    )
    db.search_results = [[vid(1), vid(2), vid(3), vid(4)]]
    db.videos = {
        vid(2): yt_video(vid(2)),
        vid(4): yt_video(vid(4), title="  "),  # 빈 제목 → 제외
    }  # vid(3)은 응답에 없음(삭제·비공개)
    out = _post(api, auth).json()["job"]
    assert out["status"] == "done" and out["profiles"][0]["collected_count"] == 1
    assert db.video_calls[0]["id"] == f"{vid(2)},{vid(3)},{vid(4)}"  # 기존 후보는 조회 안 함
    new = [c for c in db.candidates if c["first_job_id"] == db.jobs[0]["id"]]
    assert [c["video_id"] for c in new] == [vid(2)]
    assert new[0]["thumbnail_url"] == f"https://i.ytimg.com/vi/{vid(2)}/hqdefault.jpg"
    assert new[0]["category"] is None and new[0]["market"] == "KR"


def test_untrusted_ids_filtered_before_filters(api: TestClient, auth: dict, db: FakeDB):
    _only(db, P1)
    bad = ["abc),or(id", "short", "x" * 12, "한글한글한글한글한글한", 12345678901, None]
    db.search_results = [[*bad, vid(1), vid(1)]]
    db.videos = {vid(1): yt_video(vid(1))}
    _post(api, auth)
    assert db.video_calls[0]["id"] == vid(1)
    assert [c["video_id"] for c in db.candidates] == [vid(1)]


def test_no_results_marks_runs_done(api: TestClient, auth: dict, db: FakeDB):
    out = _post(api, auth).json()["job"]
    assert out["status"] == "done" and db.video_calls == []
    assert len(db.apply_calls) == 2  # 프로필마다 실행 행 done 처리


def test_overlapping_video_judged_by_all_profiles(api: TestClient, auth: dict, db: FakeDB):
    # P1(가): 최소 조회수 높음 → 제외, P2(나): 조건 통과 → 근거 대기. 대표 = P2(pending)
    db.profiles[0]["min_views"] = 10_000
    db.search_results = [[vid(1)], [vid(1), vid(2)]]  # P2 검색에도 같은 영상
    db.videos = {vid(1): yt_video(vid(1), views=500), vid(2): yt_video(vid(2), views=500)}
    out = _post(api, auth).json()["job"]
    assert out["status"] == "done"
    assert [p["collected_count"] for p in out["profiles"]] == [1, 1]
    c1 = next(c for c in db.candidates if c["video_id"] == vid(1))
    verdicts = {v["profile_id"]: v for v in db.verdicts if v["candidate_id"] == c1["id"]}
    assert verdicts[P1]["status"] == "excluded" and verdicts[P1]["reason"] == "views_min"
    assert verdicts[P2]["status"] == "pending" and verdicts[P2]["reason"] == "no_prev"
    assert c1["rep_status"] == "pending" and c1["rep_profile_id"] == P2
    # 두 번째 프로필 videos.list에는 이미 넣은 vid(1)이 없다
    assert db.video_calls[1]["id"] == vid(2)


def test_all_excluded_rep_is_first_profile(api: TestClient, auth: dict, db: FakeDB):
    for p in db.profiles:
        p["min_views"] = 10_000
    db.search_results = [[vid(1)]]
    db.videos = {vid(1): yt_video(vid(1), views=1)}
    _post(api, auth)
    c = db.candidates[0]
    assert c["rep_status"] == "excluded" and c["rep_profile_id"] == P1


# --- 실패 정리 ---------------------------------------------------------------------


def test_search_upstream_error_fails_job_and_runs(api: TestClient, auth: dict, db: FakeDB):
    db.search_error = httpx.Response(500, json={"error": {"message": "boom"}})
    resp = _post(api, auth)
    assert resp.status_code == 202
    out = resp.json()["job"]
    assert out["status"] == "failed" and out["error"] == "upstream_error"
    assert [p["status"] for p in out["profiles"]] == ["failed", "pending"]
    assert db.jobs[0]["finished_at"]


def test_second_profile_failure_keeps_first(api: TestClient, auth: dict, db: FakeDB):
    db.search_results = [[vid(1)]]
    db.videos = {vid(1): yt_video(vid(1))}
    db.search_error = httpx.Response(503)
    db.search_error_on_call = 2
    out = _post(api, auth).json()["job"]
    assert out["status"] == "failed" and out["error"] == "upstream_error"
    assert [p["status"] for p in out["profiles"]] == ["done", "failed"]
    assert len(db.candidates) == 1


def test_videos_upstream_error(api: TestClient, auth: dict, db: FakeDB):
    _only(db, P1)
    db.search_results = [[vid(1)]]
    db.videos_error = httpx.Response(500)
    out = _post(api, auth).json()["job"]
    assert out["status"] == "failed" and out["error"] == "upstream_error"


def test_db_error_mid_run_closes_job_and_raises(
    api: TestClient, auth: dict, db: FakeDB, mock_supabase
):
    _only(db, P1)
    mock_supabase.get("https://supabase.test/rest/v1/broadcaster_channels").mock(
        return_value=httpx.Response(500, json={"message": "boom"})
    )
    resp = _post(api, auth)
    assert resp.status_code == 503
    assert db.jobs[0]["status"] == "failed" and db.jobs[0]["error"] == "db_error"


def test_missing_api_key_502_no_job(mock_supabase, jwks_payload, make_token, db: FakeDB):
    from app.main import create_app
    from tests.collect_jobs.conftest import install
    from tests.conftest import JWKS_URL, make_settings

    mock_supabase.get(JWKS_URL).mock(return_value=httpx.Response(200, json=jwks_payload))
    mock_supabase.get("https://supabase.test/rest/v1/workspace_members").mock(
        return_value=httpx.Response(200, json=[{"workspace_id": db.profiles[0]["workspace_id"]}])
    )
    install(mock_supabase, db)
    with TestClient(create_app(make_settings()), raise_server_exceptions=False) as c:
        resp = _post(c, {"Authorization": f"Bearer {make_token()}"})
    assert resp.status_code == 502 and db.jobs == []


def test_api_key_never_logged(api: TestClient, auth: dict, db: FakeDB, caplog):
    caplog.set_level(logging.DEBUG)
    db.search_error = httpx.Response(400, json={"error": {"message": f"bad key {YT_KEY}"}})
    _post(api, auth)
    db.search_error = None
    db.search_results = [[vid(1)]]
    db.videos_error = httpx.Response(500)
    db.jobs[0]["created_at"] = (datetime.now(UTC) - timedelta(minutes=2)).isoformat()
    _post(api, auth, key="s-2")
    assert len(db.search_calls) == 2
    assert YT_KEY not in caplog.text


# --- 재시도·중지·만료 -----------------------------------------------------------------


def _failed_search_job(db: FakeDB, **over) -> None:
    row = job(
        status="failed",
        params=dict(SEARCH),
        error="upstream_error",
        started_at=(datetime.now(UTC) - timedelta(minutes=2)).isoformat(),
    )
    row.update(over)
    db.jobs.append(row)
    db.runs.extend([run(JOB, P1, 0, "done", 3), run(JOB, P2, 1, "failed")])


def test_retry_runs_only_remaining_profiles(api: TestClient, auth: dict, db: FakeDB):
    _failed_search_job(db)
    db.search_results = [[vid(5)]]
    db.videos = {vid(5): yt_video(vid(5))}
    resp = api.post(f"/v1/collect-jobs/{JOB}/retry", headers=auth)
    assert resp.status_code == 200, resp.json()
    out = resp.json()["job"]
    assert out["status"] == "done" and out["retry_count"] == 1 and out["error"] is None
    assert out["source"] == "youtube_search"
    assert [p["collected_count"] for p in out["profiles"]] == [3, 1]
    assert len(db.search_calls) == 1  # P2만
    assert [b["p_units"] for n, b in db.rpc_calls if n == "reserve_search"] == [100]
    assert db.jobs[0]["params"]["resume_from_profile_id"] == P2
    assert db.jobs[0]["claimed_by"] is None
    assert not any(n == "retry" for n, _ in db.rpc_calls)  # 워커용 retry RPC 미사용
    # 재판정은 이번 job의 모든 프로필로
    assert {v["profile_id"] for v in db.verdicts} == {P1, P2}


def test_retry_search_quota_429_keeps_failed(api: TestClient, auth: dict, db: FakeDB):
    _failed_search_job(db)
    db.search_units = 1_950
    resp = api.post(f"/v1/collect-jobs/{JOB}/retry", headers=auth)
    assert resp.status_code == 429 and resp.json()["code"] == "QUOTA_EXCEEDED"
    assert db.jobs[0]["status"] == "failed" and db.jobs[0]["retry_count"] == 0


@pytest.mark.parametrize("over", [{"retry_count": 3}, {"stop_requested": True}, {"status": "done"}])
def test_retry_search_rejected_409(api: TestClient, auth: dict, db: FakeDB, over: dict):
    _failed_search_job(db, **over)
    resp = api.post(f"/v1/collect-jobs/{JOB}/retry", headers=auth)
    assert resp.status_code == 409 and db.search_units == 0


def test_retry_search_nothing_left_409(api: TestClient, auth: dict, db: FakeDB):
    _failed_search_job(db)
    db.runs[1]["status"] = "done"
    assert api.post(f"/v1/collect-jobs/{JOB}/retry", headers=auth).status_code == 409


def test_retry_search_other_active_409(api: TestClient, auth: dict, db: FakeDB):
    _failed_search_job(db)
    db.jobs.append(job("00000000-0000-4000-8000-0000000000f9", status="queued"))
    resp = api.post(f"/v1/collect-jobs/{JOB}/retry", headers=auth)
    assert resp.status_code == 409 and "진행 중" in resp.json()["message"]
    assert db.search_units == 0


def test_stop_search_job_409(api: TestClient, auth: dict, db: FakeDB):
    db.jobs.append(
        job(status="running", params=dict(SEARCH), started_at=datetime.now(UTC).isoformat())
    )
    resp = api.post(f"/v1/collect-jobs/{JOB}/stop", headers=auth)
    assert resp.status_code == 409 and resp.json()["message"] == "검색 수집은 중지할 수 없습니다."
    assert db.rpc_calls == [] and db.jobs[0]["stop_requested"] is False


def test_stale_search_job_failed_upstream_error(api: TestClient, auth: dict, db: FakeDB):
    started = (datetime.now(UTC) - timedelta(minutes=6)).isoformat()
    db.jobs.append(job(status="running", params=dict(SEARCH), started_at=started))
    db.runs.append(run(JOB, P1, 0, "running"))
    assert api.get("/v1/collect-jobs/active", headers=auth).status_code == 204
    assert db.jobs[0]["status"] == "failed" and db.jobs[0]["error"] == "upstream_error"
    assert db.runs[0]["status"] == "failed"


def test_recent_search_job_not_expired(api: TestClient, auth: dict, db: FakeDB):
    started = (datetime.now(UTC) - timedelta(minutes=4)).isoformat()
    db.jobs.append(job(status="running", params=dict(SEARCH), started_at=started))
    out = api.get("/v1/collect-jobs/active", headers=auth).json()["job"]
    assert out["status"] == "running" and out["source"] == "youtube_search"


def test_vidiq_job_source(api: TestClient, auth: dict, db: FakeDB):
    db.jobs.append(job(status="queued"))
    out = api.get(f"/v1/collect-jobs/{JOB}", headers=auth).json()["job"]
    assert out["source"] == "vidiq"


# --- category(찾은 프로필 값) ------------------------------------------------------


def test_category_from_finding_profile(api: TestClient, auth: dict, db: FakeDB):
    db.profiles[0]["category"] = "게임"  # P1
    db.profiles[1]["category"] = "음악"  # P2
    db.search_results = [[vid(1)], [vid(1), vid(2)]]  # 겹친 vid(1)은 먼저 찾은 P1 값
    db.videos = {vid(1): yt_video(vid(1)), vid(2): yt_video(vid(2))}
    _post(api, auth)
    by_vid = {c["video_id"]: c for c in db.candidates}
    assert by_vid[vid(1)]["category"] == "게임" and by_vid[vid(2)]["category"] == "음악"
    v = {(x["candidate_id"], x["profile_id"]): x for x in db.verdicts}
    c1, c2 = by_vid[vid(1)]["id"], by_vid[vid(2)]["id"]
    assert v[(c1, P1)]["reason"] == "no_prev"  # 자기 검색 결과는 category로 제외되지 않음
    assert v[(c1, P2)]["reason"] == "category"  # 다른 category 프로필은 제외
    assert v[(c2, P2)]["reason"] == "no_prev" and v[(c2, P1)]["reason"] == "category"
    assert by_vid[vid(1)]["rep_profile_id"] == P1


@pytest.mark.parametrize("value", [None, "전체"])
def test_category_all_or_null_stored_null(api: TestClient, auth: dict, db: FakeDB, value):
    _only(db, P1)
    db.profiles[0]["category"] = value
    db.search_results = [[vid(1)]]
    db.videos = {vid(1): yt_video(vid(1))}
    _post(api, auth)
    assert db.candidates[0]["category"] is None


# --- 리뷰 반영: 할당량 환불·재시도 60초·처리 시간 상한 ------------------------------------


@pytest.mark.parametrize(
    "constraint", ["jobs_one_active_per_kind_idx", "jobs_workspace_id_idempotency_key_key"]
)
def test_create_conflict_releases_search_quota(
    api: TestClient, auth: dict, db: FakeDB, constraint: str
):
    db.job_insert_conflict = constraint
    resp = _post(api, auth)
    assert resp.status_code in (409, 503)
    assert ("release_search", {"p_units": 200}) in db.rpc_calls
    assert (db.search_units, db.quota_units) == (0, 0) and db.search_calls == []


def test_create_db_error_releases_search_quota(api: TestClient, auth: dict, db: FakeDB):
    db.search_units = db.quota_units = 300
    db.fail_job_insert = True
    assert _post(api, auth).status_code == 503
    assert (db.search_units, db.quota_units) == (300, 300)


def test_retry_within_60s_rate_limited(api: TestClient, auth: dict, db: FakeDB):
    _failed_search_job(db, started_at=(datetime.now(UTC) - timedelta(seconds=30)).isoformat())
    resp = api.post(f"/v1/collect-jobs/{JOB}/retry", headers=auth)
    assert resp.status_code == 429 and resp.json()["code"] == "RATE_LIMITED"
    assert db.search_units == 0 and db.jobs[0]["status"] == "failed"


def test_retry_patch_failure_releases_quota(api: TestClient, auth: dict, db: FakeDB):
    _failed_search_job(db)
    db.fail_retry_patch = True
    assert api.post(f"/v1/collect-jobs/{JOB}/retry", headers=auth).status_code == 503
    assert ("release_search", {"p_units": 100}) in db.rpc_calls
    assert db.search_units == 0 and db.search_calls == []


def test_run_deadline_fails_job_upstream_error(
    api: TestClient, auth: dict, db: FakeDB, monkeypatch
):
    import app.collect.search as search_mod

    async def slow(*args, **kwargs):
        import asyncio

        await asyncio.sleep(1)

    monkeypatch.setattr(search_mod, "SEARCH_RUN_DEADLINE_SECONDS", 0.05)
    monkeypatch.setattr(search_mod, "_run_profile", slow)
    out = _post(api, auth).json()["job"]
    assert out["status"] == "failed" and out["error"] == "upstream_error"


def test_time_budget_constants_fit_50s():
    from app.youtube import constants as c

    worst = 3 * 2 * c.YOUTUBE_CALL_TIMEOUT_SECONDS  # 프로필 3 × (검색 + videos.list)
    assert worst <= c.SEARCH_RUN_DEADLINE_SECONDS < 50


@pytest.mark.anyio
async def test_youtube_call_total_timeout():
    import asyncio

    from app.youtube.client import YouTubeUnavailable, find_video_ids

    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1)
        return httpx.Response(200, json={"items": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(slow)) as http:
        with pytest.raises(YouTubeUnavailable):
            from pydantic import SecretStr

            await find_video_ids(http, SecretStr(YT_KEY), {"part": "id"}, 0.05)
