# task-020 제작 스키마·RLS·Storage 버킷

| 항목 | 내용 |
|---|---|
| 웨이브 | W4 |
| 선행 | task-002 |
| 위험도 | 높음 |
| 보안 영향 | RLS · 마이그레이션 · Storage 비공개 버킷 · 노출 면(서명 URL 전제) |
| 담당 | builder + tester |
| 근거 | `docs/05_DATA_MODEL.md#제작-테이블`, `docs/05_DATA_MODEL.md#storage`, `docs/02b_PRODUCTION_FLOW.md`(상태), `docs/01_PRD.md#8` |
| 쓰기 허용 | `supabase/migrations/20261119000015_production.sql`(새 번호 — 000013·014는 task-019가 사용), `supabase/tests/production_rls_test.sql`, `docs/diagrams/erd.mmd`(sql2erd 재생성만), `supabase/config.toml`(storage file_size_limit 한 줄만) |

## 할 것
- `production_jobs`·`production_assets`·`edit_revisions`·`render_runs` 테이블, 상태·오류 코드 check, 모든 테이블 RLS(같은 워크스페이스만).
- `render_runs`의 queued·running 합산 워크스페이스당 1건 부분 unique, (작업, 리비전, 언어) 멱등 unique.
- `production_jobs.format`(`category`·`variety`, 기본 `category`) check와 형식별 `preset_version`, `production_assets.kind`에 `transcript`(P1 예능형 받아쓰기) 포함(`tasks/plan-variety-shorts.md` D-V1 — 나중 마이그레이션 방지).
- Storage 비공개 버킷 + 경로 규칙(작업 ID·자산 ID). 클라이언트 쓰기 권한 회수(기존 004 패턴).

## 하지 않을 것
- 적용된 마이그레이션(001~012) 수정, 서비스 롤 키를 클라이언트에 두는 것, 공개 버킷, API·웹 코드.

## 완료 조건 (실행 가능한 확인)
- [x] `supabase db reset` 후 `supabase test db` 통과(타 워크스페이스 SELECT·INSERT 거부, 동시 렌더 2건째 unique 위반, 버킷 비공개)
- [x] `~/.claude/nomad/bin/sql2erd` 재생성 후 erd.mmd에 4개 테이블 포함

## 착수 결정 (challenger 반영, 2026-11-19)
- C1 권한: 000005가 기본 권한을 회수했으므로 4개 테이블 모두 `grant select to authenticated`를 명시한다(쓰기 권한 없음). service_role 권한을 확인한다. pgTAP에 같은 워크스페이스 구성원 SELECT 성공(양성), 다른 워크스페이스 0행, anon 거부를 넣는다.
- C2 lang 선반영: `edit_revisions.lang`·`render_runs.lang`은 `text not null default 'ko' check (lang in ('ko'))`. unique는 지금부터 (job_id, lang, rev_no), 렌더 활성 unique는 (job_id, revision_id, lang). 042는 check만 넓힌다.
- C3 순환 FK: 테이블을 만든 뒤 `alter table add constraint`로 FK를 건다. 자산·리비전 참조(current_revision_id, *_asset_id, assets.render_run_id)는 `on delete set null`, 자식→job은 `on delete cascade`. pgTAP: job 삭제 시 연쇄 삭제, 자산 단독 삭제 성공.
- C4 소속 일관성: production_jobs unique(id, workspace_id). 자식은 복합 FK (job_id, workspace_id) → production_jobs. edit_revisions·production_assets·render_runs에 unique(id, job_id)를 두고, 참조(current_revision_id, render_runs.revision_id, *_asset_id)는 (id, job_id) 복합 FK로 같은 작업만 가리킨다.
- C5 updated_at 트리거 없음(000006 선례). API가 진행을 보고할 때만 설정한다. 받아쓰기 오프라인 판정용 `transcribe_updated_at`(null)을 별도로 둔다.
- C6 부분 unique 이름 확정: `render_runs_active_ws_uidx`(workspace 동시 1건), `render_runs_active_rev_uidx`(job·revision·lang). 테스트는 제약 이름까지 확인한다.
- C7 Storage: `insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types) ... on conflict do nothing`. public=false, 한도 500MB(524288000), mime 허용 목록은 05 Storage 표 기준 + json·jpeg. storage.objects에는 정책이나 alter를 두지 않는다.
- C8 업로드 한도(사용자 결정 2026-11-19, Q8 확정): **500MB**. 로컬 `supabase/config.toml` storage `file_size_limit = "500MiB"`. 원격은 Supabase Pro 플랜이 필요하므로 배포 체크리스트(`tasks/README.md#발견한 문제`)에 적는다.

## 구현 결정 (builder 보고, 팀장 수용)
- 경로 규칙은 `production_assets.storage_path` check `{ws}/{job}/{id}.[a-z0-9]{2,4}`로 DB에서도 강제한다.
- `created_by`는 FK 없는 uuid 한 칼럼(user 또는 worker)이다. 구분은 API가 맡는다.
- assets kind에 `narration`을 포함한다(05 본문). `bgm`·`image`는 task-042에서 넣는다.
- render_runs.lang과 리비전 lang의 일치는 FK로 강제하지 않는다. API가 검사한다(task-023).
- **candidate_id는 단순 FK(set null)라서 다른 워크스페이스 후보를 DB가 막지 않는다 → task-022 A-09에서 API가 소속을 확인해야 한다.**
- 자식 복합 FK는 PG17 `on delete set null (칼럼)`로 job_id를 보존한다. retry_of는 같은 작업 안에서만 참조할 수 있다.
- 기존 rls_test.sql의 테이블 수(12→16, 10→14)는 팀장이 갱신했다.
- 남은 일: 웹 DB 타입 재생성(`apps/web/src/types/db.ts`)은 웹이 제작 테이블을 쓰는 task-025에서 한다.

## 리뷰 반영 결정 (reviewer security+code ACCEPT, 🟡 후속 처리)
- 🟡1 candidate 소속: task-022에서 API로 확인한다(기록됨). DB 복합 FK(candidates unique(id, workspace_id))는 task-042 마이그레이션에 함께 넣는다.
- 🟡2 Storage 테스트 강화(storage.objects RLS on, authenticated·anon 정책 0건, allowed_mime_types): task-042 테스트에 추가한다.
- 🟡3 버킷이 이미 public으로 있으면 `on conflict do nothing`이 그대로 둔다 → 배포 체크리스트에 "public=false 확인"을 넣는다.
- 🟡4 rights_confirmed_by/at: task-022에서 API 규칙으로 정한다(url·권리 확인 시 둘 다 필수).
- 🟡5 source_url SSRF: task-031 필수 항목(기존).
