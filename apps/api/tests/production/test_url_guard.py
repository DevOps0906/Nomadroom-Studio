"""task-031 URL 원본 검사(SSRF 1차·권리 확인) 테스트.

근거: docs/01_PRD.md#8, tasks/task-031.md#착수-결정 G1·G2·G8·G9. API는 네트워크 요청을 하지 않으므로
리다이렉트·DNS 재검사는 워커(apps/worker/tests/production/test_fetch_url.py)가 맡는다.
"""

import uuid

import httpx
import pytest

from app.errors import ApiError
from app.production.url_guard import check_source_url
from app.routes.worker_production import TaskOut
from tests.production.test_jobs_api import URL, USER, api, auth, db, post_job  # noqa: F401

YT = "https://www.youtube.com/watch?v=abcdefghijk"


@pytest.mark.parametrize(
    "url",
    [
        YT,
        "https://youtube.com/watch?v=abcdefghijk",
        "https://m.youtube.com/watch?v=abcdefghijk",
        "https://youtu.be/abcdefghijk",
        "https://www.youtube.com/shorts/abcdefghijk",
        "https://WWW.YouTube.com:443/watch?v=abcdefghijk",
    ],
)
def test_allowed_youtube_urls(url):
    assert check_source_url(f"  {url} ") == url


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/v",
        "https://10.0.0.5/v",
        "https://169.254.169.254/latest/meta-data/",
        "https://[::1]/v",
        "https://[::ffff:127.0.0.1]/v",
        "http://www.youtube.com/watch?v=abcdefghijk",
        "file:///etc/passwd",
        "ftp://www.youtube.com/v",
        "javascript:alert(1)",
        "https://example.com/v",
        "https://localhost/v",
        "https://www.youtube.com.evil.test/v",
        "https://evilyoutube.com/v",
        "https://www.youtube.com@10.0.0.1/v",
        "https://user:pw@www.youtube.com/v",
        "https://www.youtube.com:8080/v",
        "https://www.youtube.com./v",
        "https://www.youtube.com\\@10.0.0.1/v",
        "https://www.you tube.com/v",
        "https://www.youtube.com/v\nHost: x",
        "https://0x7f000001/v",
        "https:///v",
        "https://www.youtube.com:99999/v",
        "https://www.youtube.com/" + "a" * 2100,
        "",
    ],
)
def test_rejected_urls(url):
    with pytest.raises(ApiError) as e:
        check_source_url(url)
    assert e.value.status_code == 400
    assert e.value.field == "source_url"


def test_error_message_has_no_url():
    with pytest.raises(ApiError) as e:
        check_source_url("https://10.1.2.3/secret-path")
    assert "10.1.2.3" not in e.value.message and "secret" not in e.value.message


def test_guard_makes_no_network_request(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("네트워크 요청 금지")

    monkeypatch.setattr("socket.getaddrinfo", boom)
    monkeypatch.setattr(httpx.Client, "send", boom)
    assert check_source_url(YT) == YT


# === A-09 POST ====================================================================


def test_create_url_job_with_rights(api, auth, db):  # noqa: F811
    r = post_job(api, auth, source_kind="url", source_url=YT, rights_confirmed=True)
    assert r.status_code == 201
    job = r.json()["job"]
    assert job["source_kind"] == "url" and job["source_url"] == YT
    assert job["rights_confirmed_by"] == USER
    assert db.jobs[0]["source_url"] == YT


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/v",
        "https://10.0.0.1/v",
        "https://169.254.169.254/v",
        "https://[::1]/v",
        "file:///etc/passwd",
        "https://vimeo.com/1",
    ],
)
def test_create_rejects_bad_url(api, auth, db, url):  # noqa: F811
    r = post_job(api, auth, source_kind="url", source_url=url, rights_confirmed=True)
    assert r.status_code == 400
    assert r.json()["code"] == "VALIDATION" and r.json()["field"] == "source_url"
    assert url not in r.text
    assert db.jobs == []


def test_create_url_without_rights_400(api, auth, db):  # noqa: F811
    r = post_job(api, auth, source_kind="url", source_url=YT, rights_confirmed=False)
    assert r.status_code == 400 and r.json()["field"] == "rights_confirmed"
    assert db.jobs == []


def test_create_url_kind_without_url_400(api, auth, db):  # noqa: F811
    r = post_job(api, auth, source_kind="url", rights_confirmed=True)
    assert r.status_code == 400 and r.json()["field"] == "source_url"


def test_create_upload_with_url_400(api, auth, db):  # noqa: F811
    r = post_job(api, auth, source_kind="upload", source_url=YT, rights_confirmed=True)
    assert r.status_code == 400 and r.json()["field"] == "source_url"
    assert db.jobs == []


# === A-09 PATCH ===================================================================


def _url_job(db) -> dict:  # noqa: F811
    return db.add_job(
        source_kind="url",
        source_url=YT,
        rights_confirmed=True,
        rights_confirmed_by=USER,
        rights_confirmed_at="2026-11-19T00:00:00+00:00",
    )


def test_patch_url_job_rights_false_400(api, auth, db):  # noqa: F811
    job = _url_job(db)
    r = api.patch(f"{URL}/{job['id']}", json={"rights_confirmed": False}, headers=auth)
    assert r.status_code == 400 and r.json()["field"] == "rights_confirmed"
    assert db.jobs[0]["rights_confirmed"] is True


def test_patch_switch_to_url_requires_rights(api, auth, db):  # noqa: F811
    job = db.add_job()
    r = api.patch(f"{URL}/{job['id']}", json={"source_kind": "url", "source_url": YT}, headers=auth)
    assert r.status_code == 400 and r.json()["field"] == "rights_confirmed"
    r = api.patch(
        f"{URL}/{job['id']}",
        json={"source_kind": "url", "source_url": YT, "rights_confirmed": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert r.json()["job"]["source_url"] == YT and r.json()["job"]["source_kind"] == "url"


def test_patch_bad_url_400(api, auth, db):  # noqa: F811
    job = _url_job(db)
    r = api.patch(
        f"{URL}/{job['id']}", json={"source_url": "https://169.254.169.254/x"}, headers=auth
    )
    assert r.status_code == 400 and r.json()["field"] == "source_url"
    assert db.jobs[0]["source_url"] == YT


def test_patch_url_job_clear_url_400(api, auth, db):  # noqa: F811
    job = _url_job(db)
    r = api.patch(f"{URL}/{job['id']}", json={"source_url": None}, headers=auth)
    assert r.status_code == 400 and r.json()["field"] == "source_url"


def test_patch_back_to_upload_clears_url(api, auth, db):  # noqa: F811
    job = _url_job(db)
    r = api.patch(f"{URL}/{job['id']}", json={"source_kind": "upload"}, headers=auth)
    assert r.status_code == 200
    assert r.json()["job"]["source_kind"] == "upload" and r.json()["job"]["source_url"] is None
    # upload가 되면 권리 해제도 허용
    r = api.patch(f"{URL}/{job['id']}", json={"rights_confirmed": False}, headers=auth)
    assert r.status_code == 200


def test_patch_upload_job_with_url_400(api, auth, db):  # noqa: F811
    job = db.add_job(rights_confirmed=True)
    r = api.patch(f"{URL}/{job['id']}", json={"source_url": YT}, headers=auth)
    assert r.status_code == 400 and r.json()["field"] == "source_url"


# === W-05 TaskOut ===================================================================


def test_task_out_carries_source_url():
    base = {
        "kind": "prepare",
        "id": str(uuid.uuid4()),
        "job_id": str(uuid.uuid4()),
        "job_kind": "general",
        "format": "category",
        "preset_version": "category-1080-v1",
        "source_kind": "url",
    }
    assert TaskOut.model_validate({**base, "source_url": YT}).source_url == YT
    assert TaskOut.model_validate(base).source_url is None


# === 리뷰 반영 ======================================================================


def test_prepare_url_job_without_rights_or_url_400(api, auth, db):  # noqa: F811
    # DB check가 막는 상태지만 API도 이중으로 거부(가짜 DB에는 check가 없다)
    for over in ({"rights_confirmed": False, "source_url": YT}, {"source_url": None}):
        job = db.add_job(**{"source_kind": "url", "rights_confirmed": True, **over})
        r = api.post(f"{URL}/{job['id']}/prepare", headers=auth)
        assert r.status_code == 400 and r.json()["field"] == "rights_confirmed"
        assert job["status"] == "draft"  # 상태 그대로(같은 dict가 가짜 DB 행)


def test_patch_concurrent_source_kind_switch_409(api, auth, db, monkeypatch):  # noqa: F811
    """읽은 뒤 다른 요청이 원본 방식을 바꿨으면(읽은 값 upload ≠ 저장 값 url) 409."""
    job = _url_job(db)
    from app.routes import production_jobs as pj

    real = pj._get_job

    async def stale(*a, **k):
        row = dict(await real(*a, **k))
        row.update(source_kind="upload", source_url=None)
        return row

    monkeypatch.setattr(pj, "_get_job", stale)
    r = api.patch(f"{URL}/{job['id']}", json={"credit": "x"}, headers=auth)
    assert r.status_code == 409
    assert db.jobs[0]["source_kind"] == "url" and db.jobs[0]["credit"] is None
