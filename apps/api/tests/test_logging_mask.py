import io
import logging
import uuid
from collections.abc import Iterator

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.auth.worker import format_token, new_secret
from app.logging_mask import mask, setup_logging
from app.main import create_app
from tests.conftest import make_settings


@pytest.fixture
def secrets_bundle(make_token) -> dict[str, str]:
    worker_secret = new_secret()
    jwt_token = make_token()
    service_key = "sb_secret_" + new_secret()
    publishable = "sb_publishable_" + new_secret()
    cookie_value = "sb-access-token=" + new_secret()
    return {
        "worker_token": format_token(uuid.uuid4(), worker_secret),
        "worker_secret": worker_secret,
        "jwt": jwt_token,
        "jwt_signature": jwt_token.rsplit(".", 1)[1],
        "service_key": service_key,
        "publishable": publishable,
        "cookie": cookie_value,
    }


@pytest.fixture
def log_stream() -> Iterator[io.StringIO]:
    stream = io.StringIO()
    handler = setup_logging(stream=stream)
    try:
        yield stream
    finally:
        logging.getLogger().removeHandler(handler)


def assert_no_secrets(output: str, bundle: dict[str, str]) -> None:
    leaked = [name for name, value in bundle.items() if value in output]
    assert leaked == [], f"마스킹 누락: {leaked}"


def test_traceback_with_secrets_is_masked(log_stream, secrets_bundle):
    b = secrets_bundle
    for name in ("uvicorn.error", "httpx", "nomadroom"):
        try:
            try:
                raise ValueError(f"worker={b['worker_token']} key={b['service_key']}")
            except ValueError as inner:
                raise RuntimeError(f"Authorization: Bearer {b['jwt']}") from inner
        except RuntimeError:
            logging.getLogger(name).exception(
                "실패 apikey=%s cookie: %s pub=%s raw=%s",
                b["service_key"],
                b["cookie"],
                b["publishable"],
                b["jwt"],
            )
        logging.getLogger(name).error("headers=%s", {"apikey": b["service_key"]})
        logging.getLogger(name).error("raw headers [(b'apikey', b'%s')]", b["service_key"])
    output = log_stream.getvalue()
    assert "Traceback" in output and "RuntimeError" in output
    assert output.count("***") >= 10
    assert_no_secrets(output, b)


def test_unhandled_exception_through_app_is_masked(log_stream, secrets_bundle):
    app = create_app(make_settings())
    router = APIRouter()

    @router.get("/_test/leak")
    async def leak() -> dict:
        raise RuntimeError(f"token {secrets_bundle['worker_token']} {secrets_bundle['jwt']}")

    app.include_router(router)
    with TestClient(app, raise_server_exceptions=False) as c:
        resp = c.get("/_test/leak", headers={"Authorization": f"Bearer {secrets_bundle['jwt']}"})
    assert resp.status_code == 500
    assert_no_secrets(resp.text, secrets_bundle)
    output = log_stream.getvalue()
    assert "RuntimeError" in output
    assert_no_secrets(output, secrets_bundle)


def test_mask_keeps_worker_id_but_hides_secret():
    wid = uuid.uuid4()
    secret = new_secret()
    out = mask(f"x {format_token(wid, secret)} y")
    assert str(wid) in out and secret not in out


def test_bare_worker_secret_is_masked(log_stream):
    secret = new_secret()
    assert len(secret) == 43
    logging.getLogger("nomadroom").error("secret=%s, raw %s.", secret, secret)
    out = log_stream.getvalue()
    assert secret not in out and out.count("***") == 2


def test_bare_secret_pattern_false_positives():
    import hashlib

    from app.auth.worker import hash_secret

    keep = [
        hash_secret(new_secret()),  # sha256 hex 64자
        str(uuid.uuid4()),
        "a" * 42,
        "b" * 44,
        hashlib.sha1(b"x").hexdigest(),  # noqa: S324 - 오탐 확인용 값
        "GET /healthz HTTP/1.1 200 OK",
    ]
    for text in keep:
        assert mask(text) == text, text


def test_httpx_logger_level_warning(log_stream):
    assert logging.getLogger("httpx").level == logging.WARNING
    logging.getLogger("httpx").info("HTTP Request: GET https://x.test/rest/v1/workers?id=eq.1")
    assert "HTTP Request" not in log_stream.getvalue()


def test_setup_logging_idempotent():
    root = logging.getLogger()
    first = setup_logging()
    try:
        second = setup_logging()
        create_app(make_settings())
        assert first is second
        assert [h for h in root.handlers if h.get_name() == first.get_name()] == [first]
    finally:
        root.removeHandler(first)


def test_uvicorn_factory_path_is_masked(monkeypatch, tmp_path, secrets_bundle):
    import uvicorn

    from tests.conftest import SERVICE_KEY, SUPABASE_URL

    monkeypatch.setenv("SUPABASE_URL", SUPABASE_URL)
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", SERVICE_KEY)
    monkeypatch.delenv("SUPABASE_JWT_ISSUER", raising=False)
    monkeypatch.chdir(tmp_path)  # 개발자 .env를 읽지 않게
    root = logging.getLogger()
    for h in [h for h in root.handlers if h.get_name() == "nomadroom-masked"]:
        root.removeHandler(h)
    # `uvicorn app.main:create_app --factory` 경로: uvicorn 기본 로그 설정 뒤 팩토리 호출
    config = uvicorn.Config("app.main:create_app", factory=True)
    config.load()
    stream = io.StringIO()
    handler = setup_logging(stream=stream)  # create_app이 단 핸들러의 출력만 바꾼다
    try:
        assert logging.getLogger("uvicorn.error").handlers == []
        assert logging.getLogger("uvicorn.access").handlers == []
        logging.getLogger("uvicorn.error").error("token %s", secrets_bundle["worker_token"])
        logging.getLogger("uvicorn.access").info("auth Bearer %s", secrets_bundle["jwt"])
        output = stream.getvalue()
        assert "token" in output and "***" in output
        assert_no_secrets(output, secrets_bundle)
    finally:
        root.removeHandler(handler)


def test_anthropic_key_is_masked(log_stream):
    """task-029 리뷰 반영: Anthropic 키(런타임 조립 가짜 값)는 로그에 남지 않는다."""
    key = "-".join(["sk", "ant", "api03", new_secret() + new_secret()])  # 상수 접힘 방지
    assert mask(f"key {key} end") == "key *** end"
    logging.getLogger("t").warning("원문 %s", key)
    out = log_stream.getvalue()
    assert key not in out and key[10:30] not in out
