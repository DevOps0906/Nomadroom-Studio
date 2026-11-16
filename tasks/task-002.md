# task-002 Supabase 스키마 · RLS 마이그레이션 · 시드 · ERD

| 항목 | 내용 |
|---|---|
| 웨이브 | W1 |
| 선행 | task-001 |
| 위험도 | 높음 |
| 보안 영향 | 민감 데이터 · 키·권한 (RLS·workers.token_hash) |
| 담당 | builder (+ intern: 시드) |
| 근거 | `docs/05_DATA_MODEL.md#공통 규칙·#테이블`, `docs/01_PRD.md#8·#9`, `docs/02_ARCHITECTURE.md#2`, `.claude/rules/db.md` |
| 쓰기 허용 | `supabase/**`, `apps/web/src/types/db.ts`, `docs/diagrams/erd.mmd`(생성만) |

## 할 것
- 05의 10개 테이블 마이그레이션(새 번호 파일), 모든 테이블 RLS, `is_workspace_member()` 헬퍼, 브라우저는 읽기만(쓰기 정책 없음), `workers`는 정책 없음(전부 거부).
- 제약: unique(workspace_id, video_id) · unique(workspace_id, idempotency_key) · observations 추가 전용 · `profiles.market` KR·JP 체크.
- 시드: 워크스페이스 1행, `broadcaster_channels` 초기 목록, KR/JP 프로필 예시. 초기 방송사 목록은 한국(KBS·MBC·SBS·JTBC·tvN 등)·일본(NHK 등) 주요 방송 채널(사용자 결정 2026-11-16). 채널 ID는 YouTube API로 확인해 시드에 넣는다.
- `sql2erd`로 ERD 생성, `supabase gen types`로 타입 생성.

## 하지 않을 것
- 적용된 마이그레이션 수정, `saved_views` 테이블, service_role을 웹·시드 스크립트 번들에 넣기, 관리 화면.

## 완료 조건 (실행 가능한 확인)
- [ ] `supabase db reset` 오류 없음
- [ ] 전 테이블 `relrowsecurity = true` 확인 SQL 통과
- [ ] 비구성원 JWT로 select 0행·insert 거부, `workers` 조회 거부 SQL 테스트 통과
- [ ] `~/.claude/nomad/bin/sql2erd supabase/migrations -o docs/diagrams/erd.mmd` 후 `mmd-check` 통과
