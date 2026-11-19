# task-042 스키마: 유형·분야·brief·제휴·권리·리비전 언어

| 항목 | 내용 |
|---|---|
| 웨이브 | W8 |
| 선행 | task-038 |
| 위험도 | 높음 |
| 보안 영향 | RLS · 마이그레이션 · 민감 데이터(제휴 링크) |
| 담당 | builder + tester |
| 근거 | `docs/05_DATA_MODEL.md#제작-테이블`·쇼핑 spec, `tasks/plan-shopping-japanese.md#팀장 설계 결정` |
| 쓰기 허용 | `supabase/migrations/2026111900XX_shopping_lang.sql`(새 번호), `supabase/tests/production_shopping_test.sql`, `docs/diagrams/erd.mmd`(재생성만) |

## 할 것
- production_jobs: kind(`general`·`shopping`)·vertical(`product`·`travel`, shopping만)·brief(jsonb)·affiliates(jsonb, 언어별)·comment_keyword. format check에 `shopping` 추가(kind와 정합 check).
- production_assets.rights(jsonb), 원본 자산 다건 허용. edit_revisions.lang·derived_from, unique를 (job, lang, rev_no)로 갱신. 기존 행은 kind=general·lang=ko 기본값. task-020 리뷰 후속: candidates unique(id, workspace_id) + production_jobs (candidate_id, workspace_id) 복합 FK, Storage 테스트 강화(storage.objects RLS·authenticated/anon 정책 0건·allowed_mime_types).

## 하지 않을 것
- 적용된 마이그레이션 수정, API·웹 코드.

## 완료 조건 (실행 가능한 확인)
- [ ] `supabase db reset` · `supabase test db` 통과(kind·format 정합 check, 타 워크스페이스 거부, ja 리비전 unique)
- [ ] sql2erd 재생성 후 새 칼럼 반영

## 착수 결정 (2026-11-20, challenger 검토 반영 · 팀장 결정)
- 순서: task-038 완료 뒤 착수, task-039(받아쓰기)보다 먼저. 마이그레이션 번호는 착수 직전 Glob으로 최대 번호 확인 후 14자리 다음 번호(예상 `20261120000021`). 039는 042 커밋 뒤 그 위에 번호를 잇는다.
- 쓰기 허용 추가: `supabase/tests/production_rls_test.sql`·`production_api_test.sql`(깨지는 assert 수정만) · `apps/web/src/types/db.ts`(재생성만) · `docs/05_DATA_MODEL.md`(확정 사항 반영만).
- S1 render_runs.lang check → ko·ja, production_assets.kind에 bgm·image 추가, storage 버킷 allowed_mime_types는 update로 image/png·webp 추가(015는 on conflict do nothing).
- S2 언어별 현재 리비전: `current_revision_id`는 ko 유지, `current_ja_revision_id` 추가 + (id, job_id) 복합 FK. 기존 RPC는 ko 경로 그대로.
- S3 이 마이그레이션에서 바꾸는 RPC는 claim의 job_kind 하드코딩 제거(칼럼 값 반환)만 — 직전 최신 본문(019·020) 위에 diff만 얹는다. kind·lang별 동작(쇼핑 원본 다건·ja 렌더·ai_draft 형식)은 044·049가 각자 새 마이그레이션으로 교체(그 작업의 쓰기 허용에 새 마이그레이션 1개 허용 — 팀장 결정).
- S4 원본 ready 1건 부분 unique 인덱스는 유지하되 kind=shopping은 RPC에서 다건 허용이 필요하면 044에서 처리(이번엔 인덱스 변경 안 함).
- S5 candidates 복합 FK는 `on delete set null (candidate_id)`, drop 전에 워크스페이스 불일치 행 0건 assert.
- S6 derived_from: (derived_from, job_id)→edit_revisions(id, job_id) FK + check(lang='ja' ⇔ derived_from not null). render_runs (revision_id, job_id, lang)→edit_revisions(id, job_id, lang) 복합 FK(unique(id, job_id, lang) 추가). 기존 unique·(id, workspace_id) 중복 생성 금지.
- S7 jsonb 형태: affiliates는 배열·url `^https://` 검사(immutable 함수 check), rights.basis 허용 목록 check, vertical·brief는 kind 정합 check, kind 변경은 update 트리거로 거부.
- S8 제휴 링크 노출: 내부 운영 도구라 같은 워크스페이스 구성원 select 허용(기존 RLS 그대로). 비밀이 아닌 추적 링크로 본다.

## 구현 결정 (2026-11-20, builder)
- 마이그레이션 `supabase/migrations/20261120000021_shopping_lang.sql`, 테스트 `supabase/tests/production_shopping_test.sql`(47건).
- affiliates: `jsonb not null default '[]'`, check는 immutable 함수 `production_affiliates_valid`(배열·원소 객체·lang ko|ja·partner 비어 있지 않음·url `^https://`). kind와 무관하게 허용(일반 작업은 빈 배열).
- brief: `null` 또는 (kind=shopping이고 객체). 쇼핑이라도 null 허용(필수 여부는 A-09/044 API). vertical은 kind=shopping ⇔ not null.
- rights: null 또는 객체, `basis`는 없음·null·허용 목록만(쇼핑 필수 여부·portrait_consent는 승인 때 API).
- kind 변경 트리거는 errcode 23514, 메시지 `production_jobs.kind is immutable`. 같은 값 update는 통과.
- render_runs: 기존 `render_runs_revision_fk`(revision_id, job_id)를 같은 이름의 (revision_id, job_id, lang)→edit_revisions(id, job_id, lang) FK로 교체(중복 FK 두지 않음). edit_revisions에 unique(id, job_id, lang) 추가.
- derived_from FK는 on delete no action(ko 단독 삭제 시 ja가 있으면 거부, job cascade 삭제는 통과 — 테스트 13).
- candidates FK: `production_jobs_candidate_id_fkey` → `production_jobs_candidate_fk`(on delete set null (candidate_id)), drop 전 불일치 0건 assert.
- `production_rls_test.sql` 7번 "lang ja는 아직 거부(23514)" → "ja run이 ko 리비전 참조 거부(23503)"로 수정.
- ERD: sql2erd는 alter table add column 중 references 없는 칼럼을 그리지 않아 새 FK 관계 2줄(derived_from·current_ja_revision_id)만 반영됨(도구 한계).

## 리뷰 반영 결정 (2026-11-20, code·security 리뷰 🔴 없음, 000021 미커밋·원격 미적용이라 직접 수정)
- R1 affiliates: 최대 20건, url `^https://[^[:space:][:cntrl:]]+$`, url 2048자 이하(`production_affiliates_valid`).
- R2 크기 상한: `pg_column_size(brief) <= 32768`(brief check), `pg_column_size(rights) <= 8192`(rights check).
- R3 rights.source_url: null(없음) 또는 `^https?://[^[:space:][:cntrl:]]+$`.
- R4 참조 리비전 언어: 생성 칼럼+복합 FK 대신 트리거 2개로 강제(칼럼·타입 추가 없음). `edit_revisions_derived_from_lang`(부모 lang=ko), `production_jobs_current_ja_revision_lang`(대상 lang=ja), 위반 23514. 전제: 리비전 lang은 생성 후 바뀌지 않는다.
- R5 check 식의 함수도 실행 권한 검사 대상이다. service_role에서 revoke하면 `permission denied for function production_affiliates_valid`가 재현돼 `grant execute ... to service_role`을 추가했고, pgTAP에서 service_role insert 성공·http 거부를 확인했다.
- pgTAP: production_shopping_test 60건(+13).
