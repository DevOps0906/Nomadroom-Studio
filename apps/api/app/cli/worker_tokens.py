"""워커 토큰 운영 CLI (service_role 환경변수 필요).

    uv run python -m app.cli.worker_tokens issue --workspace <uuid> --name <이름>
    uv run python -m app.cli.worker_tokens rotate --id <worker uuid>
    uv run python -m app.cli.worker_tokens revoke --id <worker uuid>

토큰 원문은 issue·rotate 때 stdout에 한 번만 출력한다.
로그·파일·DB에는 남기지 않는다(DB는 sha256 해시).
안내 문구는 stderr로 보낸다.
"""

import argparse
import sys
import uuid
from datetime import UTC, datetime

import httpx

from app.auth.worker import format_token, hash_secret, new_secret
from app.config import Settings
from app.supabase import rest_url, service_headers

TIMEOUT_SECONDS = 10.0


class CliError(Exception):
    pass


def _uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("UUID 형식이 아닙니다") from exc


def _headers(settings: Settings) -> dict[str, str]:
    return {
        **service_headers(settings),
        "Prefer": "return=representation",
        "Content-Type": "application/json",
    }


def _rows(resp: httpx.Response) -> list[dict]:
    if resp.status_code >= 400:
        # 응답 본문은 출력하지 않는다(상태 코드만).
        raise CliError(f"Supabase 요청 실패 (HTTP {resp.status_code})")
    try:
        data = resp.json()
    except ValueError as exc:
        raise CliError("Supabase 응답을 해석할 수 없습니다") from exc
    return data if isinstance(data, list) else []


def issue(client: httpx.Client, settings: Settings, workspace: uuid.UUID, name: str) -> str:
    worker_id = uuid.uuid4()
    secret = new_secret()
    resp = client.post(
        rest_url(settings, "workers"),
        params={"select": "id"},
        headers=_headers(settings),
        json={
            "id": str(worker_id),
            "workspace_id": str(workspace),
            "name": name,
            "token_hash": hash_secret(secret),
        },
    )
    if len(_rows(resp)) != 1:
        raise CliError("워커를 만들지 못했습니다")
    return format_token(worker_id, secret)


def rotate(client: httpx.Client, settings: Settings, worker_id: uuid.UUID) -> str:
    """같은 행의 token_hash만 바꾼다(heartbeat·jobs 연결 유지). 폐기된 워커는 회전하지 않는다."""
    secret = new_secret()
    resp = client.patch(
        rest_url(settings, "workers"),
        params={"select": "id", "id": f"eq.{worker_id}", "revoked_at": "is.null"},
        headers=_headers(settings),
        json={"token_hash": hash_secret(secret)},
    )
    if len(_rows(resp)) != 1:
        raise CliError("워커가 없거나 이미 폐기되었습니다")
    return format_token(worker_id, secret)


def revoke(client: httpx.Client, settings: Settings, worker_id: uuid.UUID) -> None:
    resp = client.patch(
        rest_url(settings, "workers"),
        params={"select": "id", "id": f"eq.{worker_id}", "revoked_at": "is.null"},
        headers=_headers(settings),
        json={"revoked_at": datetime.now(UTC).isoformat()},
    )
    if len(_rows(resp)) != 1:
        raise CliError("워커가 없거나 이미 폐기되었습니다")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="worker_tokens", description="워커 토큰 발급·회전·폐기")
    sub = parser.add_subparsers(dest="command", required=True)
    p_issue = sub.add_parser("issue", help="새 워커 행과 토큰 발급")
    p_issue.add_argument("--workspace", type=_uuid, required=True)
    p_issue.add_argument("--name", required=True)
    p_rotate = sub.add_parser("rotate", help="같은 워커의 토큰 교체")
    p_rotate.add_argument("--id", type=_uuid, required=True)
    p_revoke = sub.add_parser("revoke", help="워커 토큰 폐기(revoked_at)")
    p_revoke.add_argument("--id", type=_uuid, required=True)
    return parser


def main(argv: list[str] | None = None, client: httpx.Client | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings()  # type: ignore[call-arg]
    own_client = client is None
    client = client or httpx.Client(timeout=TIMEOUT_SECONDS)
    try:
        if args.command == "issue":
            token = issue(client, settings, args.workspace, args.name)
            print("워커 토큰(이번 한 번만 표시, 워커 설정에만 보관):", file=sys.stderr)
            print(token)
        elif args.command == "rotate":
            token = rotate(client, settings, args.id)
            print("새 워커 토큰(이번 한 번만 표시, 이전 토큰은 즉시 무효):", file=sys.stderr)
            print(token)
        else:
            revoke(client, settings, args.id)
            print("폐기했습니다.", file=sys.stderr)
        return 0
    except CliError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1
    except httpx.TimeoutException, httpx.NetworkError:
        if args.command == "rotate":
            # 요청이 반영됐는지 알 수 없다(이전 토큰이 이미 무효일 수 있음).
            print("오류: 결과를 확인할 수 없음 — rotate를 다시 실행하세요", file=sys.stderr)
        else:
            print("오류: Supabase에 연결할 수 없습니다", file=sys.stderr)
        return 1
    except httpx.HTTPError:
        print("오류: Supabase에 연결할 수 없습니다", file=sys.stderr)
        return 1
    finally:
        if own_client:
            client.close()


if __name__ == "__main__":
    sys.exit(main())
