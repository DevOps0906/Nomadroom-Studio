import json
import logging
import uuid

import httpx
import pytest
import respx

from app.auth.worker import hash_secret, parse_token
from app.cli import worker_tokens
from tests.conftest import SERVICE_KEY, SUPABASE_URL, WORKSPACE_ID

WORKERS_URL = f"{SUPABASE_URL}/rest/v1/workers"
WORKER_ID = uuid.UUID("33333333-3333-4333-8333-333333333333")


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("SUPABASE_URL", SUPABASE_URL)
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", SERVICE_KEY)
    monkeypatch.delenv("SUPABASE_JWT_ISSUER", raising=False)
    monkeypatch.chdir(tmp_path)  # 개발자 .env를 읽지 않게


def run(argv, capsys):
    with httpx.Client() as client:
        code = worker_tokens.main(argv, client=client)
    out, err = capsys.readouterr()
    return code, out, err


def test_issue_prints_token_once_and_stores_hash(capsys, caplog):
    caplog.set_level(logging.DEBUG)
    with respx.mock() as router:
        route = router.post(WORKERS_URL).mock(
            side_effect=lambda req: httpx.Response(
                201, json=[{"id": json.loads(req.content)["id"]}]
            )
        )
        code, out, err = run(["issue", "--workspace", str(WORKSPACE_ID), "--name", "pc-1"], capsys)
    assert code == 0
    token = out.strip()
    assert out.count(token) == 1 and token not in err
    worker_id, secret = parse_token(token)
    body = json.loads(route.calls.last.request.content)
    assert body["id"] == str(worker_id)
    assert body["workspace_id"] == str(WORKSPACE_ID)
    assert body["token_hash"] == hash_secret(secret)
    assert secret not in route.calls.last.request.content.decode()
    assert secret not in caplog.text


def test_rotate_updates_same_row(capsys):
    with respx.mock() as router:
        route = router.patch(WORKERS_URL).mock(
            return_value=httpx.Response(200, json=[{"id": str(WORKER_ID)}])
        )
        code, out, _ = run(["rotate", "--id", str(WORKER_ID)], capsys)
    assert code == 0
    worker_id, secret = parse_token(out.strip())
    assert worker_id == WORKER_ID
    req = route.calls.last.request
    assert req.url.params["id"] == f"eq.{WORKER_ID}"
    assert req.url.params["revoked_at"] == "is.null"
    assert json.loads(req.content) == {"token_hash": hash_secret(secret)}


def test_revoke_sets_revoked_at(capsys):
    with respx.mock() as router:
        route = router.patch(WORKERS_URL).mock(
            return_value=httpx.Response(200, json=[{"id": str(WORKER_ID)}])
        )
        code, out, _ = run(["revoke", "--id", str(WORKER_ID)], capsys)
    assert code == 0 and out == ""
    assert "revoked_at" in json.loads(route.calls.last.request.content)


def test_rotate_missing_or_revoked_fails(capsys):
    with respx.mock() as router:
        router.patch(WORKERS_URL).mock(return_value=httpx.Response(200, json=[]))
        code, out, err = run(["rotate", "--id", str(WORKER_ID)], capsys)
    assert code == 1 and out == "" and "오류" in err


def test_invalid_uuid_rejected(capsys):
    with pytest.raises(SystemExit):
        run(["revoke", "--id", "not-uuid"], capsys)


def test_non_json_response_fails_with_fixed_message(capsys):
    with respx.mock() as router:
        router.patch(WORKERS_URL).mock(
            return_value=httpx.Response(200, content=b"<html>proxy RAW-BODY</html>")
        )
        code, out, err = run(["revoke", "--id", str(WORKER_ID)], capsys)
    assert code == 1 and out == ""
    assert "오류: Supabase 응답을 해석할 수 없습니다" in err
    assert "RAW-BODY" not in err


@pytest.mark.parametrize(
    "exc", [httpx.ReadTimeout("t"), httpx.ConnectTimeout("t"), httpx.ConnectError("c")]
)
def test_rotate_unknown_result_on_timeout_or_connect_failure(capsys, exc):
    with respx.mock() as router:
        router.patch(WORKERS_URL).mock(side_effect=exc)
        code, out, err = run(["rotate", "--id", str(WORKER_ID)], capsys)
    assert code == 1 and out == ""
    assert "결과를 확인할 수 없음 — rotate를 다시 실행하세요" in err
