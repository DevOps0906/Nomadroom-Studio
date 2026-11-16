import time

import httpx
import pytest
import respx
from cryptography.hazmat.primitives import serialization

from app.auth.authz import not_found_if_other_workspace
from app.errors import ApiError
from tests.conftest import (
    JWKS_URL,
    KID,
    OTHER_WORKSPACE_ID,
    SUPABASE_URL,
    USER_ID,
    WORKSPACE_ID,
    unsigned_token,
)

MEMBERS_URL = f"{SUPABASE_URL}/rest/v1/workspace_members"


@pytest.fixture
def jwks_route(mock_supabase: respx.MockRouter, jwks_payload: dict) -> respx.Route:
    return mock_supabase.get(JWKS_URL).mock(return_value=httpx.Response(200, json=jwks_payload))


@pytest.fixture
def member_route(mock_supabase: respx.MockRouter) -> respx.Route:
    return mock_supabase.get(MEMBERS_URL).mock(
        return_value=httpx.Response(200, json=[{"workspace_id": str(WORKSPACE_ID)}])
    )


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def assert_401(resp: httpx.Response) -> None:
    assert resp.status_code == 401
    assert resp.json() == {"code": "UNAUTHENTICATED", "message": "인증이 필요합니다."}


def test_valid_token_resolves_workspace(client, jwks_route, member_route, make_token):
    resp = client.get("/_test/me", headers=auth(make_token()))
    assert resp.status_code == 200
    assert resp.json() == {"user_id": str(USER_ID), "workspace_id": str(WORKSPACE_ID)}
    req = member_route.calls.last.request
    assert req.url.params["user_id"] == f"eq.{USER_ID}"
    assert "limit" not in req.url.params
    # sb_secret_ 키는 apikey 헤더로만
    assert "apikey" in req.headers and "authorization" not in req.headers


def test_no_token(client, jwks_route):
    assert_401(client.get("/_test/me"))
    assert_401(client.get("/_test/me", headers={"Authorization": "Basic abc"}))
    assert jwks_route.call_count == 0


def test_expired(client, jwks_route, member_route, make_token):
    past = int(time.time()) - 3600
    assert_401(client.get("/_test/me", headers=auth(make_token(iat=past - 600, exp=past))))
    assert member_route.call_count == 0


def test_alg_none(client, jwks_route, member_route):
    assert_401(client.get("/_test/me", headers=auth(unsigned_token("none"))))
    assert member_route.call_count == 0


def test_hs256_signed_with_public_key(client, jwks_route, member_route, ec_key):
    pem = ec_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    assert_401(client.get("/_test/me", headers=auth(unsigned_token("HS256", key=pem))))
    assert member_route.call_count == 0


def test_unknown_kid_refetch_throttled(client, jwks_route, member_route, make_token):
    # 첫 요청: TTL 조회 1회 + (방금 조회했으므로) 재조회 없음
    assert_401(client.get("/_test/me", headers=auth(make_token(kid="unknown"))))
    assert_401(client.get("/_test/me", headers=auth(make_token(kid="unknown2"))))
    assert jwks_route.call_count == 1
    assert member_route.call_count == 0


@pytest.mark.anyio
async def test_unknown_kid_refetch_once_per_60s(jwks_payload):
    from app.auth.jwks import JwksCache, UnknownKid

    now = [0.0]
    cache = JwksCache(JWKS_URL, clock=lambda: now[0])
    with respx.mock() as router:
        route = router.get(JWKS_URL).mock(return_value=httpx.Response(200, json=jwks_payload))
        async with httpx.AsyncClient() as c:
            await cache.get_key(c, KID)
            now[0] = 61.0
            with pytest.raises(UnknownKid):
                await cache.get_key(c, "new-kid")
            assert route.call_count == 2
            now[0] = 90.0
            with pytest.raises(UnknownKid):
                await cache.get_key(c, "new-kid")
            assert route.call_count == 2
            now[0] = 700.0  # TTL 경과 → 재조회
            await cache.get_key(c, KID)
            assert route.call_count == 3


def test_missing_aud(client, jwks_route, member_route, make_token):
    assert_401(client.get("/_test/me", headers=auth(make_token(aud=None))))


def test_wrong_aud(client, jwks_route, member_route, make_token):
    assert_401(client.get("/_test/me", headers=auth(make_token(aud="anon"))))


def test_other_issuer(client, jwks_route, member_route, make_token):
    assert_401(client.get("/_test/me", headers=auth(make_token(iss="http://evil.test/auth/v1"))))


def test_missing_sub(client, jwks_route, member_route, make_token):
    assert_401(client.get("/_test/me", headers=auth(make_token(sub=None))))


def test_non_uuid_sub(client, jwks_route, member_route, make_token):
    assert_401(client.get("/_test/me", headers=auth(make_token(sub="not-a-uuid"))))


def test_non_authenticated_role(client, jwks_route, member_route, make_token):
    assert_401(client.get("/_test/me", headers=auth(make_token(role="service_role"))))


def test_not_member_403(client, jwks_route, mock_supabase, make_token):
    mock_supabase.get(MEMBERS_URL).mock(return_value=httpx.Response(200, json=[]))
    resp = client.get("/_test/me", headers=auth(make_token()))
    assert resp.status_code == 403
    assert resp.json()["code"] == "FORBIDDEN"


def test_multiple_memberships_403(client, jwks_route, mock_supabase, make_token):
    rows = [{"workspace_id": str(WORKSPACE_ID)}, {"workspace_id": str(OTHER_WORKSPACE_ID)}]
    mock_supabase.get(MEMBERS_URL).mock(return_value=httpx.Response(200, json=rows))
    resp = client.get("/_test/me", headers=auth(make_token()))
    assert resp.status_code == 403
    assert resp.json()["code"] == "FORBIDDEN"


def test_other_workspace_resource_404(client, jwks_route, member_route, make_token):
    ok = client.get(f"/_test/resources/{WORKSPACE_ID}", headers=auth(make_token()))
    assert ok.status_code == 200
    resp = client.get(f"/_test/resources/{OTHER_WORKSPACE_ID}", headers=auth(make_token()))
    assert resp.status_code == 404
    assert resp.json() == {"code": "NOT_FOUND", "message": "찾을 수 없습니다."}


def test_not_found_helper_unit():
    not_found_if_other_workspace(WORKSPACE_ID, WORKSPACE_ID)
    not_found_if_other_workspace(str(WORKSPACE_ID), WORKSPACE_ID)
    for other in (OTHER_WORKSPACE_ID, None, "garbage"):
        with pytest.raises(ApiError) as exc:
            not_found_if_other_workspace(other, WORKSPACE_ID)
        assert exc.value.status_code == 404 and exc.value.code == "NOT_FOUND"


def test_jwks_unavailable_503(client, mock_supabase, make_token):
    mock_supabase.get(JWKS_URL).mock(return_value=httpx.Response(500))
    resp = client.get("/_test/me", headers=auth(make_token()))
    assert resp.status_code == 503
    assert resp.json()["code"] == "UPSTREAM_ERROR"


def test_jwks_without_usable_keys_503(client, mock_supabase, make_token):
    hs = {"keys": [{"kty": "oct", "kid": KID, "k": "c2VjcmV0", "alg": "HS256"}]}
    mock_supabase.get(JWKS_URL).mock(return_value=httpx.Response(200, json=hs))
    resp = client.get("/_test/me", headers=auth(make_token()))
    assert resp.status_code == 503


def test_membership_lookup_failure_503(client, jwks_route, mock_supabase, make_token):
    mock_supabase.get(MEMBERS_URL).mock(side_effect=httpx.ConnectError("down"))
    resp = client.get("/_test/me", headers=auth(make_token()))
    assert resp.status_code == 503


def test_nbf_in_future_401(client, jwks_route, member_route, make_token):
    future = int(time.time()) + 300
    assert_401(client.get("/_test/me", headers=auth(make_token(nbf=future))))
    assert member_route.call_count == 0


def test_aud_array(client, jwks_route, member_route, make_token):
    ok = client.get("/_test/me", headers=auth(make_token(aud=["other", "authenticated"])))
    assert ok.status_code == 200
    assert_401(client.get("/_test/me", headers=auth(make_token(aud=["other", "anon"]))))


@pytest.mark.anyio
async def test_jwks_failure_cooldown_and_no_stale_keys(jwks_payload):
    from app.auth.jwks import JwksCache, JwksUnavailable

    now = [0.0]
    cache = JwksCache(JWKS_URL, clock=lambda: now[0])
    with respx.mock() as router:
        route = router.get(JWKS_URL).mock(return_value=httpx.Response(200, json=jwks_payload))
        async with httpx.AsyncClient() as c:
            await cache.get_key(c, KID)
            route.mock(side_effect=httpx.ConnectError("down"))
            now[0] = 700.0  # TTL 경과 + 조회 실패: 만료된 키를 쓰지 않고 실패
            with pytest.raises(JwksUnavailable):
                await cache.get_key(c, KID)
            assert route.call_count == 2
            now[0] = 759.0  # 60초 안: 재조회 없이 바로 실패
            with pytest.raises(JwksUnavailable):
                await cache.get_key(c, KID)
            assert route.call_count == 2
            route.mock(side_effect=None, return_value=httpx.Response(200, json=jwks_payload))
            now[0] = 760.0  # 60초 경과: 재조회
            await cache.get_key(c, KID)
            assert route.call_count == 3


class _HangingClient:
    """조회마다 delay초 걸린 뒤 타임아웃으로 실패하는 가짜 클라이언트."""

    def __init__(self, delay: float):
        self.delay = delay
        self.calls = 0

    async def get(self, url: str) -> httpx.Response:
        import anyio

        self.calls += 1
        await anyio.sleep(self.delay)
        raise httpx.ConnectTimeout("timeout")


@pytest.mark.anyio
async def test_concurrent_requests_do_not_queue_on_jwks_failure():
    import anyio

    from app.auth.jwks import JwksCache, JwksUnavailable

    cache = JwksCache(JWKS_URL)
    fake = _HangingClient(delay=0.3)
    results: list[str] = []

    async def one() -> None:
        try:
            await cache.get_key(fake, KID)  # type: ignore[arg-type]
        except JwksUnavailable:
            results.append("503")

    start = time.monotonic()
    async with anyio.create_task_group() as tg:
        for _ in range(10):
            tg.start_soon(one)
    elapsed = time.monotonic() - start
    assert results == ["503"] * 10
    assert fake.calls == 1
    assert elapsed < 0.3 * 2  # 줄 섰다면 0.3 x 10초
