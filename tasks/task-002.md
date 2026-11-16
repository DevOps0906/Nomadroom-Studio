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
- 05의 11개 테이블 마이그레이션(새 번호 파일), 모든 테이블 RLS, `is_workspace_member()` 헬퍼, 브라우저는 읽기만(쓰기 정책 없음), `workers`는 정책 없음(전부 거부).
- 제약: unique(workspace_id, video_id) · unique(workspace_id, idempotency_key) · observations 추가 전용 · `profiles.market` KR·JP 체크.
- 시드: 워크스페이스 1행, `broadcaster_channels` 초기 목록, KR/JP 프로필 예시. 초기 방송사 목록은 한국(KBS·MBC·SBS·JTBC·tvN 등)·일본(NHK 등) 주요 방송 채널(사용자 결정 2026-11-16). 채널 ID는 YouTube API로 확인해 시드에 넣는다.
- 시드(개발·데모용, `supabase/seed.sql`만): 시안 예시 후보 5건(예능·스포츠·영화·드라마·일상, 한국 4·일본 1) + 후보별 두 시점 관측값(11-09 → 11-16): 「한마디에 분위기가 바뀐 순간」 예능 450,000→452,700 C.C · 「마지막 동작이 갈랐던 승부」 스포츠 710,000→714,260 C.C · 「한 장면으로 설명하는 반전의 구조」 영화·드라마 이전 없음→270,000 라이선스 미확인 · 「도시 산책 중 발견한 작은 반전」 일상·일본 200,000→225,000 표준 · 「대화의 흐름이 바뀐 두 번째 장면」 예능 300,000→301,800 C.C 사용한 소재. 이전 관측 없는 1건(근거 대기)·사용한 소재 1건 포함. task-009 보류 중에도 화면 단계에서 확인할 데이터가 된다(`docs/06_AGENT_PLAN.md#3`).
- `sql2erd`로 ERD 생성, `supabase gen types`로 타입 생성.

## 하지 않을 것
- 적용된 마이그레이션 수정, `saved_views` 테이블, service_role을 웹·시드 스크립트 번들에 넣기, 관리 화면.

## 완료 조건 (실행 가능한 확인)
- [x] `supabase db reset` 오류 없음
- [x] 전 테이블 `relrowsecurity = true` 확인 SQL 통과
- [x] 비구성원 JWT로 select 0행·insert 거부, `workers` 조회 거부 SQL 테스트 통과
- [x] `~/.claude/nomad/bin/sql2erd supabase/migrations -o docs/diagrams/erd.mmd` 후 `mmd-check` 통과

## 구현 결정 (팀장, 2026-11-16 · challenger 검토 반영)
- 도구: `npx supabase@3.1.0`(버전 고정). 타입 생성은 bash 리다이렉트(UTF-8). RLS 테스트는 `supabase/tests/*.sql` pgTAP → `supabase test db`.
- FK on delete: `workspace_id`→workspaces cascade · workspace_members.user_id→auth.users cascade · jobs.requested_by→auth.users set null · candidates.rep_profile_id·first_job_id set null · jobs.claimed_by set null · worker_heartbeats.worker_id cascade, current_job_id set null · verdicts.candidate_id·profile_id cascade, prev_/curr_observation_id set null(180일 정리 허용) · observations.candidate_id cascade, **observations.job_id no action**(추가 전용 트리거와 충돌 방지) · job_profile_runs.job_id·profile_id cascade.
- 추가 전용: observations에 BEFORE UPDATE 트리거로 예외(service_role 포함). DELETE는 허용(180일 정리).
- 권한: anon·authenticated에서 모든 테이블 insert·update·delete·truncate revoke, anon은 select도 revoke. `workers`는 authenticated select도 revoke(조회 = permission denied).
- 헬퍼 `public.is_workspace_member(ws uuid)`: security invoker · stable · `set search_path = ''` · 스키마 붙인 이름. execute는 public·anon revoke, authenticated만 grant.
- 인덱스: unique가 앞 열로 덮지 않는 모든 `workspace_id`와 FK 열에 인덱스. 모든 테이블 `comment on table` 한 줄.
- jobs 동시 실행: 부분 unique 인덱스 (workspace_id, kind) where status in ('queued','running').
- 시드: workspace UUID 고정. auth.users·workspace_members는 넣지 않음(구성원은 task-012 초대에서). candidate_verdicts·rep_status는 시드 프로필로 `01_PRD.md#9`를 계산한 값과 일치. 관측 시각 11-09·11-16 같은 시각(UTC, 정확히 7일).
- 방송사 channel_id: 공개 채널 페이지에서 확인한 값만 넣는다. 확인 못 한 채널은 빼고 보고(추측 금지).
- RLS 테스트: 테스트 트랜잭션 안에서 auth.users 2명 생성(구성원·비구성원) → 구성원 select > 0행(양성 대조), 비구성원 0행·insert 거부, workers select 거부, observations update 예외.
- seed.sql은 로컬 전용(`db push --include-seed` 금지).

## 이후 작업 메모 (보안 리뷰 🟡, 이번 범위 밖)
- 자식 행 workspace_id = 부모 workspace_id를 DB가 보장하지 않음 → 다중 워크스페이스 전에 복합 FK(task-003 이후 API에서 우선 강제).
- observations 추가 전용은 UPDATE만 막음. delete 후 재삽입·180일 조건은 API(task-009·정리 작업)에서 강제.
- 원격 프로젝트의 가입 차단·이메일 확인 설정은 배포 시 대시보드에서 확인.
- 함수 실행 권한: 전역 기본값으로 PUBLIC execute 회수(000005). 브라우저가 호출할 함수는 authenticated grant를 명시한다.
