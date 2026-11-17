import httpx
import pytest
import respx

from tests.conftest import JWKS_URL, SUPABASE_URL, WORKSPACE_ID

REST = f"{SUPABASE_URL}/rest/v1"
MEMBERS_URL = f"{REST}/workspace_members"


@pytest.fixture(autouse=True)
def auth_routes(request: pytest.FixtureRequest, jwks_payload: dict) -> None:
    if request.node.get_closest_marker("integration"):
        return  # 통합 테스트는 실제 로컬 Supabase를 쓴다
    mock_supabase: respx.MockRouter = request.getfixturevalue("mock_supabase")
    mock_supabase.get(JWKS_URL).mock(return_value=httpx.Response(200, json=jwks_payload))
    mock_supabase.get(MEMBERS_URL).mock(
        return_value=httpx.Response(200, json=[{"workspace_id": str(WORKSPACE_ID)}])
    )


@pytest.fixture
def headers(make_token) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token()}"}
