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
- 셸 재구현 금지(task-018 사용).

## 완료 조건 (실행 가능한 확인)
- [x] `pnpm typecheck && pnpm lint && pnpm test` 통과(컴포넌트 상태: 기본·오류·429·로딩)
- [x] 다른 Origin 헤더의 POST가 403인 테스트 통과
- [x] 번들 검색 `grep -r service_role apps/web/.next` 0건
- [x] `~/.claude/nomad/bin/shot`으로 3구간 캡처 확인

## 구현 결정 (2026-11-16 · challenger 검토 반영, ★는 사용자 결정)
- ★세션은 서버 전용: 브라우저 Supabase 클라이언트 없음(02#2 갱신). 클라이언트 팩토리는 `src/server/supabase/**` 한 곳(`import "server-only"`), cookieOptions(httpOnly·SameSite=Lax·운영 Secure)를 서버 클라이언트와 proxy 양쪽이 같은 팩토리로 쓴다. 환경변수 `SUPABASE_URL`·`SUPABASE_PUBLISHABLE_KEY`·`APP_ORIGIN`(NEXT_PUBLIC 없음).
- ★로그인 시도 제한: 웹 서버에서 IP별 제한(5분 10회, 메모리, 단일 인스턴스 가정) → 넘으면 429 문구. IP는 `x-forwarded-for` 첫 값(신뢰 프록시 뒤 가정, 없으면 'unknown' 한 버킷). Supabase 429도 같은 문구.
- 인증 경계: `src/proxy.ts`(Next 16)에서 세션 갱신·미로그인 리다이렉트. matcher는 `_next/static`·`_next/image`·favicon·이미지 확장자 제외, 공개 경로 `/login`·`/forgot-password`·`/auth/confirm`. **이중 방어**: `(dashboard)/layout.tsx`에서 서버 세션 확인(없으면 redirect('/login')).
- 사용자 확인은 `getClaims()`(로컬 ES256 확인됨 → 로컬 검증). 세션 철회는 exp까지 유효(task-003과 동일 기준).
- next 검증 함수 `safeNext()`: 디코드 후 `/`로 시작, 2번째 문자가 `/`·`\` 아님, 제어문자·공백 없음, `new URL(next, APP_ORIGIN).origin === APP_ORIGIN`. proxy와 Server Action 양쪽에서 적용, 실패 시 `/`.
- 로그인 폼: `useActionState`. 오류 시 이메일은 상태로 돌려받아 `defaultValue`로 다시 채움(비밀번호는 돌려주지 않음 = 비움). 로딩은 `useFormStatus().pending`(버튼 비활성+스피너). 표시 컴포넌트는 props(`pending`·`error`·`email`)로 상태를 받는 순수 컴포넌트로 분리해 renderToStaticMarkup로 기본·오류·429·로딩을 테스트.
- 비밀번호 재설정: recovery 메일 템플릿을 `{{ .SiteURL }}/auth/confirm?token_hash={{ .TokenHash }}&type=recovery&next=/reset-password`로 설정 — 로컬은 `supabase/config.toml`+`supabase/templates/recovery.html`, 운영 대시보드 반영은 배포 체크 항목. `/auth/confirm`은 verifyOtp(type=recovery만 허용) 후 `/reset-password`. `/reset-password`는 recovery 직후 세션만 허용(쿠키 표식 `pw_recovery`, 10분)이고, 일반 로그인 세션이면 접근 불가 → `/`.
- 이미 로그인한 사용자가 `/login`·`/forgot-password` 접근 → `/`로.
- 소속 없는 사용자: `(dashboard)/layout.tsx`에서 workspace_members 0행이면 "워크스페이스 접근 권한이 없습니다. 관리자에게 문의하세요" 안내 + 로그아웃 버튼만 표시.
- Origin 검사 `assertSameOrigin(req)`: `Origin` 헤더가 `APP_ORIGIN`과 정확히 같아야 함(없거나 다르면 403). Server Action은 Next 자체 검사에 맡긴다(문서에 명시). 로그아웃은 `POST /auth/signout` Route Handler로 이 함수를 쓴다.
- 쓰기 허용 확장: `apps/web/src/proxy.ts`, `apps/web/src/server/**`, `apps/web/src/app/(dashboard)/layout.tsx`(세션·소속 확인만, 셸 구조 변경 금지), `apps/web/src/app/auth/**`, `supabase/config.toml`(auth.email.template.recovery만), `supabase/templates/**`, `apps/web/package.json`·lock, `.env.example`(추가만).
- 완료 확인 추가: 로컬 Inbucket(Mailpit)으로 재설정 메일 링크를 끝까지 따라가 비밀번호 변경 → 새 비밀번호로 로그인 성공(수동 또는 스크립트, 결과 보고).

## 리뷰 반영 결정 (2026-11-16, ★는 사용자 결정)
- 🔴 safeNext: decodeURIComponent 제거(searchParams·formData는 이미 디코드됨). URL 정규화 **결과** pathname을 다시 검사(`//`·`\` 시작, 제어문자). `safeNext(safeNext(x)) === safeNext(x)` 성질 테스트 + `/.//evil.com`·`/%2E//evil.com`·다중 인코딩 입력.
- 재설정 완료 시 `signOut({scope:"global"})`. 로그아웃 Route·재설정에서 signOut error가 나면 sb-* 쿠키를 직접 삭제.
- `/auth/confirm` GET은 확인 화면만("비밀번호 재설정 계속" 버튼), verifyOtp는 POST(Server Action). 템플릿에서 `next=` 제거.
- IP 제한: 버킷 상한 초과 시 가장 오래된 것부터 제거(O(1) 근사 가능), 상한 테스트. 배포 체크: 프록시가 X-Forwarded-For를 덮어쓰는지 확인.
- proxy matcher `\.`로 수정. 리다이렉트 응답에도 setAll이 넣은 헤더(Cache-Control 등) 복사.
- config.toml(로컬): `secure_password_change = true`, `minimum_password_length = 10`. 운영 대시보드 동일 설정은 배포 체크.
- 로그인 실패 기록: 서버 로그에 `{event:"login_failed", reason}`만(이메일·IP 원문·비밀번호 금지).
- ★`/terms` 공개 페이지(PUBLIC_PATHS 추가): 내부 운영자 전용 도구·수집 개인정보는 로그인 이메일뿐·문의는 관리자 — 짧은 안내.
- 접근성: 오류 문구 id + 입력칸 aria-describedby, forgot·reset 폼에도 aria-invalid. 제품명은 "Nomadroom Studio"로 통일(문서 제목 포함).
- 오류 시 비밀번호는 유지하지 않는다(보안상 의도, spec "입력 유지"는 이메일에 적용).
- 테스트 보강: 안전한 next(`/monitor`) 유지, limiter 테스트 간 상태 격리, proxy 공개 경로·리다이렉트·쿠키·헤더 단위 테스트.
- 배포 체크 항목은 `tasks/README.md#발견한 문제`에 한 줄씩 남긴다(팀장).
