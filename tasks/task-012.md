# task-012 AUTH-01 로그인

| 항목 | 내용 |
|---|---|
| 웨이브 | W3 |
| 선행 | task-001, task-002 |
| 위험도 | 높음 |
| 보안 영향 | 노출 면 · 민감 데이터 (인터넷 공개 `/login`, 세션 쿠키, CSRF) |
| 담당 | builder (+ codex-reviewer design) |
| 근거 | `spec AUTH-01`, `docs/04_API.md#A-01`, `docs/01_PRD.md#8` 웹 열, `design/wireframes/AUTH-01.html` |
| 쓰기 허용 | `apps/web/src/app/(auth)/**`, `apps/web/src/middleware.ts`, `apps/web/src/lib/supabase/**`, `apps/web/src/components/auth/**` |

## 할 것
- `spec AUTH-01`의 구성 블록·상태·다음 화면대로 로그인·비밀번호 재설정 화면(가입 화면 없음). Supabase 서버 클라이언트, httpOnly 세션 쿠키.
- 미로그인 접근 시 `/login` 리다이렉트, POST·PUT·PATCH·DELETE Route Handler용 Origin 검사 공용 함수.
- 로그인 시도 제한은 Supabase Auth 기본 제한(팀장 결정 2026-11-16), 429 문구 표시. 토큰은 3구간 반응형·토큰 색만.

## 하지 않을 것
- 회원가입·소셜 로그인·역할 UI, service_role을 웹에서 사용.

## 완료 조건 (실행 가능한 확인)
- [ ] `pnpm typecheck && pnpm lint && pnpm test` 통과(컴포넌트 상태: 기본·오류·429·로딩)
- [ ] 다른 Origin 헤더의 POST가 403인 테스트 통과
- [ ] 번들 검색 `grep -r service_role apps/web/.next` 0건
- [ ] `~/.claude/nomad/bin/shot`으로 3구간 캡처 확인
