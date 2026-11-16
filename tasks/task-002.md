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
- 시드(개발·데모용, `supabase/seed.sql`만): 시안 예시 후보 5건(예능·스포츠·영화·드라마·일상, 한국 4·일본 1) + 후보별 두 시점 관측값(11-09 → 11-16): 「한마디에 분위기가 바뀐 순간」 예능 450,000→452,700 C.C · 「마지막 동작이 갈랐던 승부」 스포츠 710,000→714,260 C.C · 「한 장면으로 설명하는 반전의 구조」 영화·드라마 이전 없음→270,000 라이선스 미확인 · 「도시 산책 중 발견한 작은 반전」 일상·일본 200,000→225,000 표준 · 「대화의 흐름이 바뀐 두 번째 장면」 예능 300,000→301,800 C.C 사용한 소재. 이전 관측 없는 1건(근거 대기)·사용한 소재 1건 포함. task-009 보류 중에도 화면 단계에서 확인할 데이터가 된다(`docs/06_AGENT_PLAN.md#3`).
- `sql2erd`로 ERD 생성, `supabase gen types`로 타입 생성.

## 하지 않을 것
- 적용된 마이그레이션 수정, `saved_views` 테이블, service_role을 웹·시드 스크립트 번들에 넣기, 관리 화면.

## 완료 조건 (실행 가능한 확인)
- [ ] `supabase db reset` 오류 없음
- [ ] 전 테이블 `relrowsecurity = true` 확인 SQL 통과
- [ ] 비구성원 JWT로 select 0행·insert 거부, `workers` 조회 거부 SQL 테스트 통과
- [ ] `~/.claude/nomad/bin/sql2erd supabase/migrations -o docs/diagrams/erd.mmd` 후 `mmd-check` 통과
