from app.config import Settings
from app.supabase import service_headers
from tests.conftest import make_settings


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_validation_becomes_400_without_input(client):
    resp = client.get("/_test/items", params={"page": "SECRET-INPUT-VALUE"})
    assert resp.status_code == 400
    body = resp.json()
    assert body == {"code": "VALIDATION", "message": "입력값이 올바르지 않습니다.", "field": "page"}
    assert "SECRET-INPUT-VALUE" not in resp.text


def test_404_and_405_format(client):
    resp = client.get("/nope")
    assert resp.status_code == 404
    assert resp.json() == {"code": "NOT_FOUND", "message": "찾을 수 없습니다."}
    resp = client.post("/healthz")
    assert resp.status_code == 405
    assert resp.json()["code"] == "METHOD_NOT_ALLOWED"


def test_500_hides_internal_detail(client):
    resp = client.get("/_test/boom")
    assert resp.status_code == 500
    assert resp.json() == {"code": "INTERNAL", "message": "서버 오류가 발생했습니다."}
    assert "secret detail" not in resp.text and "path" not in resp.text


def test_service_headers_by_key_kind():
    new = service_headers(make_settings())
    assert set(new) == {"apikey"}
    legacy_key = ".".join(["eyJ" + "a" * 8, "b" * 8, "c" * 8])  # 레거시 JWT 형태의 더미
    legacy = service_headers(make_settings(supabase_service_role_key=legacy_key))
    assert legacy["apikey"] == legacy_key
    assert legacy["Authorization"] == f"Bearer {legacy_key}"


def test_settings_reject_wrong_key_kind():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        make_settings(supabase_service_role_key="sb_publishable_abc")


def test_issuer_default_and_override():
    assert make_settings().jwt_issuer == "https://supabase.test/auth/v1"
    s: Settings = make_settings(supabase_jwt_issuer="https://x.test/auth/v1")
    assert s.jwt_issuer == "https://x.test/auth/v1"


def test_docs_disabled_by_default(client):
    for path in ("/docs", "/redoc", "/openapi.json"):
        resp = client.get(path)
        assert resp.status_code == 404, path
        assert resp.json()["code"] == "NOT_FOUND"


def test_docs_enabled_by_setting():
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app(make_settings(api_docs_enabled=True))
    with TestClient(app) as c:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert c.get(path).status_code == 200, path


def test_settings_error_hides_key_input():
    import pytest
    from pydantic import ValidationError

    raw = "sb_publishable_SHOULD-NOT-APPEAR-IN-ERROR"
    with pytest.raises(ValidationError) as exc:
        make_settings(supabase_service_role_key=raw)
    assert raw not in str(exc.value) and raw not in repr(exc.value)


def test_supabase_url_requires_https_except_local():
    import pytest
    from pydantic import ValidationError

    for ok in (
        "https://abc.supabase.co",
        "http://localhost:54321",
        "http://127.0.0.1:54321",
        "http://[::1]:54321",
    ):
        assert make_settings(supabase_url=ok).supabase_url == ok
    for bad in ("http://abc.supabase.co", "http://localhost.evil.test", "ftp://x.test", "x"):
        with pytest.raises(ValidationError):
            make_settings(supabase_url=bad)


def test_validation_field_allowlist(client):
    ok = client.post("/_test/scores", json={"good_key.1": "x"})
    assert ok.status_code == 400 and ok.json()["field"] == "good_key.1"
    for key in ("<script>alert(1)</script>", "a b", "가나다", "a" * 65):
        resp = client.post("/_test/scores", json={key: "x"})
        assert resp.status_code == 400
        assert resp.json() == {"code": "VALIDATION", "message": "입력값이 올바르지 않습니다."}
        assert key not in resp.text
