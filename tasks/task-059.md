# task-059 A-12 저장 낙관적 잠금 강화(ko·ja)

| 항목 | 내용 |
|---|---|
| 웨이브 | W11(안정화) |
| 선행 | task-049 |
| 위험도 | 높음(마이그레이션·API·웹 계약) |
| 보안 영향 | 없음(데이터 유실 방지) |
| 담당 | builder + tester |
| 근거 | `tasks/README.md#발견한 문제` 2026-11-20 A-12 행, `docs/04_API.md` A-12 행, 000016 `save_revision`·000027 `save_ja_revision` |
| 쓰기 허용 | 새 마이그레이션 `20261120000030_revision_lock.sql`·pgTAP, `apps/api/app/routes/production_jobs.py`(A-12 PUT), API 테스트, `apps/web/src/components/production/**`·`apps/web/src/server/api/production.ts`·`apps/web/src/app/api/production-jobs/[id]/revision/**`(base 값 전달), `docs/04_API.md` A-12 행 |

## 할 것
- 미승인 리비전을 같은 rev_no로 두 사람이 동시에 저장하면 앞선 편집이 유실되는 문제 해결: PUT에 `base_updated_at`(GET 응답의 리비전 `updated_at`)을 함께 받아 RPC가 잠금 안에서 비교, 다르면 409(NR011). ko·ja 둘 다.
- 웹 편집 화면 3종·ja 패널이 읽은 `updated_at`을 보내고 409면 "다른 곳에서 먼저 수정됨 — 새로고침" 안내(입력 유지).

## 하지 않을 것
- 적용된 마이그레이션 수정, 자동 병합.

## 완료 조건
- [ ] pgTAP: 같은 base로 두 번 저장하면 두 번째 NR011(ko·ja) · API·웹 테스트 · api pytest·web test·test db 통과

## 착수 결정 (팀장 2026-11-20, challenger REVISE 반영)
- L1 노출(🔴1·2): 리비전 `updated_at`을 A-12 GET·PUT 응답, 저장 RPC 반환, A-14(AI 초안)·A-20(번역) 응답, 웹 relay(revision·ai-draft·translate)·편집 page.tsx까지 전달. 쓰기 허용에 `apps/api/app/routes/production_ai.py`, `apps/web/src/app/(dashboard)/production/[id]/edit/page.tsx`, `apps/web/src/app/api/production-jobs/[id]/{ai-draft,translate}/**`, `docs/04_API.md` A-14·A-20 행 추가.
- L2 RPC(🔴3): `20261120000030_revision_lock.sql`에서 기존 save 함수(000016 6인자·000027 ja)를 **drop 후** base_updated_at 인자를 가진 새 시그니처로 생성(본문은 각 정본 복사), revoke(public·anon·authenticated)·grant(service_role) 재선언. 오버로드 0개를 pgTAP으로 확인.
- L3 비교(🟡): rev_no 비교 바로 옆에서 승인·미승인 **두 분기 모두** `v_rev.updated_at <> p_base_updated_at`(timestamptz)이면 NR011. 웹은 값을 가공 없이 문자열 그대로 전달(Date 변환 금지), API는 timestamptz로 파싱해 넘김. 마이크로초 값 GET→PUT 왕복 테스트.
- L4 필수(사람 질문 → 팀장 기본값): `base_updated_at` **필수**(미전송 422). 배포 순서 마이그레이션 → API → 웹(로컬 단일 운영자), 04_API에 명시.
- L5 웹(🟡): 저장·AI 초안·번역 성공 후 상태의 updated_at 갱신, 편집 폼 key에 updated_at 포함, 409면 입력 유지 + "다른 곳에서 먼저 수정됨 — 새로고침" 안내. 테스트: 연속 저장 2회 성공, 낡은 base 409(ko·ja·승인본 저장).

## 구현 결정 (builder 2026-11-20)
- 000030: 두 save 함수 drop → `(…, p_base_rev_no integer, p_base_updated_at timestamptz, p_spec, p_validation)` 7인자로 생성, 본문은 정본 복사 + rev_no 비교 줄에 `or v_rev.updated_at <> p_base_updated_at`(승인·미승인 공통), 반환 JSON에 `updated_at`. `_ai_draft_json`(000025)·`_translate_json`(000027)은 시그니처가 같아 `create or replace`로 `updated_at`만 추가(A-14·A-20 응답). 권한 revoke·grant 재선언.
- L4 "미전송 422": 이 API는 `RequestValidationError`를 전부 400 `VALIDATION`(field)으로 바꾸는 규약(`app/errors.py`)이라 **400 field=`base_updated_at`**로 구현. `AwareDatetime`이라 시간대 없는 값도 400. 409 field는 기존대로 `base_rev_no`.
- 웹: 값은 문자열 그대로 전달(relay는 비어 있지 않은 64자 이하 문자열만 확인). 편집 폼 3종은 `updatedAt` 상태를 저장·AI 초안 성공 때 갱신, ko 폼 page key에 `updated_at` 포함. ja 패널은 저장 뒤 새로고침하지 않고 응답으로 상태 갱신(`model.applySaved`), key는 rev_no만(리뷰 🔴: 재마운트 입력 유실 방지, 번역 새 rev 때만 재마운트·dirty면 기존 확인창). 409는 기존 충돌 안내(ko 3종) 유지, ja 패널은 `SAVE_CONFLICT` 문구로 안내하고 입력 유지.
- pgTAP은 한 트랜잭션이라 `now()`가 고정 → 같은 base 두 번째 NR011은 시드의 과거 updated_at으로 검증, 마이크로초 1 차이 NR011 포함.
