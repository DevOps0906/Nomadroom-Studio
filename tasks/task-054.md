# task-054 AI 영상 생성 연동

| 항목 | 내용 |
|---|---|
| 웨이브 | W9 |
| 선행 | task-047, Q16(플랫폼·예산·약관 확정) |
| 위험도 | 높음 |
| 보안 영향 | 외부 계약(AI 영상 API) · 새 키(서버 전용) · 비용 발생 · 사진 외부 전송 |
| 담당 | builder + tester |
| 근거 | `tasks/plan-shopping-japanese.md#여행 영상 생성과 비용`, `docs/research/shopping-shorts-notion-analysis.md#7`, `docs/04_API.md`·`docs/05_DATA_MODEL.md`(generation_runs) |
| 쓰기 허용 | `apps/api/app/production/videogen/**`, `apps/api/app/routes/production_jobs.py`(생성 요청), `supabase/migrations/`(새 번호, generation_runs), `apps/api/app/production/validation_shopping.py`(gen.unreviewed만), 해당 테스트, PROD-02S 컷별 "AI 생성"·검수 체크 |

## 할 것
- 착수 전: Q16(플랫폼 1개·월 예산·작업당 상한·상업 이용 약관) 확정, 유료 키 발급은 사용자 승인.
- 플랫폼 어댑터 인터페이스 + 품질 등급 2개(quality=힉스필드, economy=그록) 어댑터. 컷별 등급 선택·등급별 예상 비용. 입력 = 공식 사진 자산(권리 basis 확인됨) + 프롬프트, 결과 = `source_upload`(basis `ai_generated`, 플랫폼·모델·요청 ID·비용).
- 예상 비용 표시 → 확인 후 요청, 작업 상한·월 예산 초과 거부, 멱등 키, generation_runs 기록, 컷별 사람 검수 체크 3항목(물리 오류·불가능 앵글·실제 사진 대조, 전부 체크해야 승인).

## 하지 않을 것
- 키를 웹·워커에 두기, 예산 확인 없는 생성, 권리 미확인 사진 전송, 세 번째 플랫폼 추가(Q16 확정 전).

## 완료 조건 (실행 가능한 확인)
- [ ] `cd apps/api && pytest -q tests/production/test_videogen.py` 통과(모의 플랫폼: 정상·실패·예산 초과 거부·멱등 재요청 무과금)
- [ ] `supabase test db` 통과(generation_runs RLS)
