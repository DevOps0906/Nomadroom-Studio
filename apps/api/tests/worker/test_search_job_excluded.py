"""task-019: 검색 수집 job은 워커가 수령하지 않고 오프라인 만료 대상도 아니다."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from tests.worker.conftest import JOB, FakeDB, auth, job

CLAIM = "/worker/v1/jobs/claim"
SEARCH = {"limit": 200, "source": "youtube_search"}


def test_claim_skips_search_job(api: TestClient, db: FakeDB):
    # 정상 흐름에서는 검색 job이 queued·retrying이 되지 않지만(DB 제약), 필터로도 배제한다.
    db.jobs.append(job(status="queued", params=SEARCH))
    assert api.post(CLAIM, headers=auth()).status_code == 204
    assert db.jobs[0]["status"] == "queued" and db.jobs[0]["claimed_by"] is None


def test_claim_still_takes_vidiq_job(api: TestClient, db: FakeDB):
    db.jobs.append(job(status="queued", params={"limit": 200}))
    resp = api.post(CLAIM, headers=auth())
    assert resp.status_code == 200 and resp.json()["job"]["id"] == JOB


def test_running_search_job_not_expired_as_offline(api: TestClient, db: FakeDB):
    started = (datetime.now(UTC) - timedelta(minutes=4)).isoformat()
    db.jobs.append(job(status="running", params=SEARCH, claimed_by=None, started_at=started))
    api.post(CLAIM, headers=auth())
    assert db.jobs[0]["status"] == "running" and db.jobs[0].get("error") is None
