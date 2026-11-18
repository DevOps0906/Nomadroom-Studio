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
- production_assets.rights(jsonb), 원본 자산 다건 허용. edit_revisions.lang·derived_from, unique를 (job, lang, rev_no)로 갱신. 기존 행은 kind=general·lang=ko 기본값.

## 하지 않을 것
- 적용된 마이그레이션 수정, API·웹 코드.

## 완료 조건 (실행 가능한 확인)
- [ ] `supabase db reset` · `supabase test db` 통과(kind·format 정합 check, 타 워크스페이스 거부, ja 리비전 unique)
- [ ] sql2erd 재생성 후 새 칼럼 반영
