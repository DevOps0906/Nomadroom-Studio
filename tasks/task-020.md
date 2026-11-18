# task-020 제작 스키마·RLS·Storage 버킷

| 항목 | 내용 |
|---|---|
| 웨이브 | W4 |
| 선행 | task-002 |
| 위험도 | 높음 |
| 보안 영향 | RLS · 마이그레이션 · Storage 비공개 버킷 · 노출 면(서명 URL 전제) |
| 담당 | builder + tester |
| 근거 | `docs/05_DATA_MODEL.md#제작-테이블`, `docs/05_DATA_MODEL.md#storage`, `docs/02b_PRODUCTION_FLOW.md`(상태), `docs/01_PRD.md#8` |
| 쓰기 허용 | `supabase/migrations/20261118000013_production.sql`(새 번호), `supabase/tests/production_rls_test.sql`, `docs/diagrams/erd.mmd`(sql2erd 재생성만) |

## 할 것
- `production_jobs`·`production_assets`·`edit_revisions`·`render_runs` 테이블, 상태·오류 코드 check, 모든 테이블 RLS(같은 워크스페이스만).
- `render_runs`의 queued·running 합산 워크스페이스당 1건 부분 unique, (작업, 리비전, 언어) 멱등 unique.
- `production_jobs.format`(`category`·`variety`, 기본 `category`) check와 형식별 `preset_version`, `production_assets.kind`에 `transcript`(P1 예능형 받아쓰기) 포함(`tasks/plan-variety-shorts.md` D-V1 — 나중 마이그레이션 방지).
- Storage 비공개 버킷 + 경로 규칙(작업 ID·자산 ID). 클라이언트 쓰기 권한 회수(기존 004 패턴).

## 하지 않을 것
- 적용된 마이그레이션(001~012) 수정, 서비스 롤 키를 클라이언트에 두는 것, 공개 버킷, API·웹 코드.

## 완료 조건 (실행 가능한 확인)
- [ ] `supabase db reset` 후 `supabase test db` 통과(타 워크스페이스 SELECT·INSERT 거부, 동시 렌더 2건째 unique 위반, 버킷 비공개)
- [ ] `~/.claude/nomad/bin/sql2erd` 재생성 후 erd.mmd에 4개 테이블 포함
