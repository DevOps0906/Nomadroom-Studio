import uuid

import httpx
import pytest
import respx

from app.auth.worker import format_token, hash_secret, new_secret, parse_token
from tests.conftest import SUPABASE_URL, WORKSPACE_ID

WORKERS_URL = f"{SUPABASE_URL}/rest/v1/workers"
WORKER_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")


@pytest.fixture
def secret() -> str:
    return new_secret()


def worker_row(secret: str, revoked_at: str | None = None) -> dict:
    return {
        "id": str(WORKER_ID),
        "workspace_id": str(WORKSPACE_ID),
        "token_hash": hash_secret(secret),
        "revoked_at": revoked_at,
    }


def call(client, token: str) -> httpx.Response:
    return client.get("/_test/worker", headers={"Authorization": f"Bearer {token}"})


def assert_401(resp: httpx.Response) -> None:
    assert resp.status_code == 401
    assert resp.json() == {"code": "UNAUTHENTICATED", "message": "인증이 필요합니다."}


def test_valid_worker_token(client, mock_supabase: respx.MockRouter, secret):
    route = mock_supabase.get(WORKERS_URL).mock(
        return_value=httpx.Response(200, json=[worker_row(secret)])
    )
    resp = call(client, format_token(WORKER_ID, secret))
    assert resp.status_code == 200
    assert resp.json() == {"worker_id": str(WORKER_ID), "workspace_id": str(WORKSPACE_ID)}
    req = route.calls.last.request
    assert req.url.params["id"] == f"eq.{WORKER_ID}"
    assert secret not in str(req.url)


def test_no_token(client, mock_supabase):
    route = mock_supabase.get(WORKERS_URL)
    assert_401(client.get("/_test/worker"))
    assert route.call_count == 0


@pytest.mark.parametrize(
    "token",
    [
        "no-dot-token",
        "not-a-uuid.abcdefghijklmnopqrstuvwxyz",
        f"{WORKER_ID}.",
        ".secret",
        f"{WORKER_ID.hex}.secret",  # 하이픈 없는 UUID도 거부(36자 정규형만)
        "00000000-0000-4000-8000-000000000001' or 1=1--.secret",
    ],
)
def test_malformed_token_never_queries(client, mock_supabase, token):
    route = mock_supabase.get(WORKERS_URL)
    assert_401(call(client, token))
    assert route.call_count == 0


def test_unknown_worker(client, mock_supabase, secret):
    mock_supabase.get(WORKERS_URL).mock(return_value=httpx.Response(200, json=[]))
    assert_401(call(client, format_token(WORKER_ID, secret)))


def test_hash_mismatch(client, mock_supabase, secret):
    mock_supabase.get(WORKERS_URL).mock(
        return_value=httpx.Response(200, json=[worker_row(new_secret())])
    )
    assert_401(call(client, format_token(WORKER_ID, secret)))


def test_revoked(client, mock_supabase, secret):
    row = worker_row(secret, revoked_at="2026-11-16T00:00:00+00:00")
    mock_supabase.get(WORKERS_URL).mock(return_value=httpx.Response(200, json=[row]))
    assert_401(call(client, format_token(WORKER_ID, secret)))


def test_parse_token_roundtrip(secret):
    assert parse_token(format_token(WORKER_ID, secret)) == (WORKER_ID, secret)
    assert len(hash_secret(secret)) == 64


@pytest.mark.parametrize(
    "mock",
    [
        {"side_effect": httpx.ConnectError("down")},
        {"return_value": httpx.Response(500)},
        {"return_value": httpx.Response(200, content=b"not json")},
    ],
)
def test_worker_lookup_failure_503(client, mock_supabase, secret, mock):
    mock_supabase.get(WORKERS_URL).mock(**mock)
    resp = call(client, format_token(WORKER_ID, secret))
    assert resp.status_code == 503
    assert resp.json()["code"] == "UPSTREAM_ERROR"


def test_worker_row_without_workspace_id_503(client, mock_supabase, secret):
    row = worker_row(secret)
    del row["workspace_id"]
    mock_supabase.get(WORKERS_URL).mock(return_value=httpx.Response(200, json=[row]))
    resp = call(client, format_token(WORKER_ID, secret))
    assert resp.status_code == 503
    assert resp.json()["code"] == "UPSTREAM_ERROR"
