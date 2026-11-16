"""Authorization: Bearer 헤더 파싱(없거나 형식이 틀리면 None)."""

from fastapi import Request


def bearer_token(request: Request) -> str | None:
    value = request.headers.get("authorization")
    if not value:
        return None
    scheme, _, token = value.partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token or " " in token:
        return None
    return token
