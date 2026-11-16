import base64
import hashlib
import hmac
import json
import time
import uuid
from collections.abc import Iterator
from typing import Any

import jwt
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

from app.auth.authz import not_found_if_other_workspace
from app.auth.user import CurrentUser, get_current_user
from app.auth.worker import CurrentWorker, get_current_worker
from app.config import Settings
from app.main import create_app

SUPABASE_URL = "https://supabase.test"
ISSUER = f"{SUPABASE_URL}/auth/v1"
JWKS_URL = f"{ISSUER}/.well-known/jwks.json"
KID = "test-kid-1"
USER_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
WORKSPACE_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
OTHER_WORKSPACE_ID = uuid.UUID("00000000-0000-4000-8000-000000000002")
SERVICE_KEY = "sb_secret_" + "x" * 32


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "supabase_url": SUPABASE_URL,
        "supabase_service_role_key": SERVICE_KEY,
        "supabase_jwt_issuer": None,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


@pytest.fixture(scope="session")
def ec_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


@pytest.fixture(scope="session")
def jwks_payload(ec_key: ec.EllipticCurvePrivateKey) -> dict:
    jwk = jwt.algorithms.ECAlgorithm.to_jwk(ec_key.public_key(), as_dict=True)
    jwk.update({"kid": KID, "alg": "ES256", "use": "sig"})
    return {"keys": [jwk]}


def claims(**overrides: Any) -> dict:
    now = int(time.time())
    base = {
        "sub": str(USER_ID),
        "aud": "authenticated",
        "iss": ISSUER,
        "role": "authenticated",
        "iat": now,
        "exp": now + 600,
    }
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None}


@pytest.fixture
def make_token(ec_key: ec.EllipticCurvePrivateKey):
    def _make(kid: str = KID, **overrides: Any) -> str:
        return jwt.encode(claims(**overrides), ec_key, algorithm="ES256", headers={"kid": kid})

    return _make


def unsigned_token(alg: str, key: bytes | None = None, kid: str = KID) -> str:
    header = b64url(json.dumps({"alg": alg, "typ": "JWT", "kid": kid}).encode())
    payload = b64url(json.dumps(claims()).encode())
    signing_input = f"{header}.{payload}".encode()
    sig = b64url(hmac.new(key, signing_input, hashlib.sha256).digest()) if key else ""
    return f"{header}.{payload}.{sig}"


@pytest.fixture
def mock_supabase() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as router:
        yield router


def add_test_routes(app: FastAPI) -> None:
    """테스트 전용 라우트(운영 코드에는 없음)."""
    router = APIRouter()

    @router.get("/_test/me")
    async def me(user: CurrentUser = Depends(get_current_user)) -> dict:
        return {"user_id": str(user.user_id), "workspace_id": str(user.workspace_id)}

    @router.get("/_test/resources/{owner_ws}")
    async def resource(owner_ws: uuid.UUID, user: CurrentUser = Depends(get_current_user)) -> dict:
        not_found_if_other_workspace(owner_ws, user.workspace_id)
        return {"ok": True}

    @router.get("/_test/worker")
    async def worker(w: CurrentWorker = Depends(get_current_worker)) -> dict:
        return {"worker_id": str(w.worker_id), "workspace_id": str(w.workspace_id)}

    @router.get("/_test/items")
    async def items(page: int) -> dict:
        return {"page": page}

    @router.post("/_test/scores")
    async def scores(body: dict[str, int]) -> dict:
        return {"n": len(body)}

    @router.get("/_test/boom")
    async def boom() -> dict:
        raise RuntimeError("C:\\internal\\path secret detail")

    app.include_router(router)


@pytest.fixture
def client(mock_supabase: respx.MockRouter) -> Iterator[TestClient]:
    app = create_app(make_settings())
    add_test_routes(app)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
