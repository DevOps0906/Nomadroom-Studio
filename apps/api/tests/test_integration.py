"""로컬 supabase start 실제 토큰 통합 테스트(-m integration).

키는 셸 환경변수로만 넘긴다(파일에 쓰지 않는다):
  SUPABASE_URL · SUPABASE_SERVICE_ROLE_KEY · SUPABASE_PUBLISHABLE_KEY
"""

import os
import secrets
import uuid
from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from app.auth.worker import format_token, hash_secret, new_secret
from app.config import Settings
from app.main import create_app
from app.supabase import rest_url, service_headers
from tests.conftest import add_test_routes

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def settings() -> Settings:
    missing = [
        n
        for n in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_PUBLISHABLE_KEY")
        if not os.environ.get(n)
    ]
    if missing:
        pytest.fail(f"통합 테스트 환경변수 없음: {missing}")
    return Settings(_env_file=None)  # type: ignore[call-arg]


@pytest.fixture(scope="module")
def admin(settings: Settings) -> Iterator[httpx.Client]:
    with httpx.Client(base_url=settings.supabase_url, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def world(settings: Settings, admin: httpx.Client) -> Iterator[dict]:
    """테스트 사용자·워크스페이스·소속·워커를 만들고 끝나면 지운다."""
    headers = {**service_headers(settings), "Prefer": "return=representation"}
    email = f"it-{uuid.uuid4().hex[:12]}@example.test"
    password = secrets.token_urlsafe(24)
    r = admin.post(
        "/auth/v1/admin/users",
        headers=headers,
        json={"email": email, "password": password, "email_confirm": True},
    )
    assert r.status_code in (200, 201), r.status_code
    user_id = r.json()["id"]
    ws_id = str(uuid.uuid4())
    worker_id = uuid.uuid4()
    worker_secret = new_secret()
    try:
        r = admin.post(
            rest_url(settings, "workspaces"),
            headers=headers,
            json={"id": ws_id, "name": "integration-test"},
        )
        assert r.status_code == 201, r.status_code
        r = admin.post(
            rest_url(settings, "workspace_members"),
            headers=headers,
            json={"workspace_id": ws_id, "user_id": user_id},
        )
        assert r.status_code == 201, r.status_code
        r = admin.post(
            rest_url(settings, "workers"),
            headers=headers,
            json={
                "id": str(worker_id),
                "workspace_id": ws_id,
                "name": "it-worker",
                "token_hash": hash_secret(worker_secret),
            },
        )
        assert r.status_code == 201, r.status_code
        r = admin.post(
            "/auth/v1/token",
            params={"grant_type": "password"},
            headers={"apikey": os.environ["SUPABASE_PUBLISHABLE_KEY"]},
            json={"email": email, "password": password},
        )
        assert r.status_code == 200, r.status_code
        yield {
            "access_token": r.json()["access_token"],
            "user_id": user_id,
            "workspace_id": ws_id,
            "worker_token": format_token(worker_id, worker_secret),
        }
    finally:
        admin.delete(
            rest_url(settings, "workspaces"), params={"id": f"eq.{ws_id}"}, headers=headers
        )
        admin.delete(f"/auth/v1/admin/users/{user_id}", headers=headers)


@pytest.fixture(scope="module")
def client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings)
    add_test_routes(app)
    with TestClient(app) as c:
        yield c


def test_real_supabase_token_200(client: TestClient, world: dict):
    resp = client.get("/_test/me", headers={"Authorization": f"Bearer {world['access_token']}"})
    assert resp.status_code == 200
    assert resp.json() == {"user_id": world["user_id"], "workspace_id": world["workspace_id"]}


def test_real_worker_token_200(client: TestClient, world: dict):
    resp = client.get("/_test/worker", headers={"Authorization": f"Bearer {world['worker_token']}"})
    assert resp.status_code == 200
    assert resp.json()["workspace_id"] == world["workspace_id"]
    bad = world["worker_token"][:-2] + "xx"
    resp = client.get("/_test/worker", headers={"Authorization": f"Bearer {bad}"})
    assert resp.status_code == 401
