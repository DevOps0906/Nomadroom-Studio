# apps/api — Nomadroom Studio API

FastAPI 서버. Supabase JWT 검증(JWKS, ES256·RS256만), `workspace_members` 소속으로 워크스페이스 결정, 워커 토큰 인증, 로그 마스킹.

## 진행 현황
- task-003: 뼈대·`/healthz`·공통 오류 형식·사용자/워커 인증 의존성·워커 토큰 CLI·로그 마스킹 (비즈니스 엔드포인트 없음)

## 버전 (2026-11-16, `uv.lock`이 정본)
Python 3.14 (uv 관리) · FastAPI 0.163.1 · Starlette 1.10.0 · Pydantic 2.14.3 · pydantic-settings 2.16.3 · PyJWT 2.15.1 (+cryptography 50.0.2) · httpx 0.28.1 · uvicorn 0.54.0
개발: pytest 9.2.0 · anyio 4.16.0 · respx 0.23.1 · ruff 0.17.5

## 실행
```bash
cd apps/api
uv sync
uv run python -m app            # 루트 로그 마스킹 적용 후 uvicorn 기동 (API_HOST·API_PORT)
uv run pytest -q                # 단위 테스트(외부 호출은 respx로 대체)
uv run ruff check . && uv run ruff format --check .
```
환경변수 이름은 루트 `.env.example` 참고. 값은 셸 환경변수나 `apps/api/.env`(커밋 금지)로만.

## 통합 테스트 (로컬 `supabase start` 실제 토큰)
키를 파일에 쓰지 않고 셸 환경변수로만 넘긴다.
```bash
eval "$(npx supabase@3.1.0 status -o env)"
SUPABASE_URL="$API_URL" SUPABASE_SERVICE_ROLE_KEY="$SECRET_KEY" \
SUPABASE_PUBLISHABLE_KEY="$PUBLISHABLE_KEY" uv run pytest -q -m integration
```

## 워커 토큰 운영 (service_role 환경변수 필요)
```bash
uv run python -m app.cli.worker_tokens issue  --workspace <workspace uuid> --name <이름>
uv run python -m app.cli.worker_tokens rotate --id <worker uuid>   # 같은 행 해시 교체
uv run python -m app.cli.worker_tokens revoke --id <worker uuid>   # revoked_at 설정
```
토큰(`<worker_id>.<secret>`)은 stdout에 한 번만 출력된다. DB에는 sha256(secret)만 저장한다.
