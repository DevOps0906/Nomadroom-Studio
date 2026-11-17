"""A-08 로컬 Supabase 통합 테스트(-m integration). 시드(supabase/seed.sql) 필요.

키는 셸 환경변수로만. 시드 후보 201의 used를 바꿨다가 끝나면 원래대로 되돌린다.
"""

from datetime import datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.supabase import rest_url, service_headers
from tests.read_api.test_read_api_integration import (  # noqa: F401  (fixture 재사용)
    api,
    other_candidate_id,
    seed_token,
)
from tests.test_integration import admin, settings  # noqa: F401

pytestmark = pytest.mark.integration

CID = "00000000-0000-4000-8000-000000000201"


def _used_count(api: TestClient, h: dict) -> int:  # noqa: F811  (fixture 이름 재사용)
    resp = api.get("/v1/candidates", headers=h)
    assert resp.status_code == 200, resp.json()
    return resp.json()["counts"]["used"]


def test_toggle_used_changes_counts(
    api: TestClient,  # noqa: F811
    seed_token: str,  # noqa: F811
    other_candidate_id: str,  # noqa: F811
    settings: Settings,  # noqa: F811
    admin: httpx.Client,  # noqa: F811
):
    h = {"Authorization": f"Bearer {seed_token}"}
    try:
        base = _used_count(api, h)
        first = api.patch(f"/v1/candidates/{CID}/used", headers=h, json={"used": True})
        assert first.status_code == 200, first.json()
        fb = first.json()
        assert fb["used"] is True and fb["used_at"] is not None
        assert _used_count(api, h) == base + 1

        again = api.patch(f"/v1/candidates/{CID}/used", headers=h, json={"used": True})
        assert again.json() == fb  # 멱등: used_at 유지

        off = api.patch(f"/v1/candidates/{CID}/used", headers=h, json={"used": False})
        assert off.json() == {"id": CID, "used": False, "used_at": None}
        assert _used_count(api, h) == base

        re = api.patch(f"/v1/candidates/{CID}/used", headers=h, json={"used": True}).json()
        assert datetime.fromisoformat(re["used_at"]) > datetime.fromisoformat(fb["used_at"])

        for used in (True, False):
            other = api.patch(
                f"/v1/candidates/{other_candidate_id}/used", headers=h, json={"used": used}
            )
            assert other.status_code == 404 and other.json()["code"] == "NOT_FOUND"
    finally:
        admin.patch(
            rest_url(settings, "candidates"),
            headers=service_headers(settings),
            params={"id": f"eq.{CID}"},
            json={"used": False, "used_at": None},
        )
