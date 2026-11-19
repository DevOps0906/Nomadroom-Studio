# task-040 예능형 AI 초안

| 항목 | 내용 |
|---|---|
| 웨이브 | W7 |
| 선행 | task-039, task-029 |
| 위험도 | 높음 |
| 보안 영향 | 외부 계약(Claude) · 대사 텍스트 외부 전송(01#8) |
| 담당 | builder + tester |
| 근거 | `docs/04_API.md#A-14`, `docs/01_PRD.md#8`, `docs/05_DATA_MODEL.md#예능형-spec` |
| 쓰기 허용 | `apps/api/app/production/ai_draft*.py`, `apps/api/tests/production/test_ai_draft_variety.py` |

## 할 것
- A-14 format 분기: 입력 transcript 텍스트·저해상도 시트·후보 제목, 출력 variety spec(구조화 JSON) → 서버 검증 후 새 리비전(origin=ai_draft). 호출 상한 Q7 공용.

## 하지 않을 것
- 원본 영상·음성 전송, 키를 웹·워커에 두기, 검증 우회 저장.

## 완료 조건 (실행 가능한 확인)
- [ ] `cd apps/api && pytest -q tests/production/test_ai_draft_variety.py` 통과(Claude 응답 모의: 정상·스키마 위반·상한 초과)

## 착수 메모 (2026-11-20, 팀장)
- 선행 task-039 보류(GPL) → 입력은 transcript 대신 현재 리비전의 대사 자막 텍스트(사용자 입력, 비신뢰 데이터). 없으면 시트·제목만.

## 착수 결정 (2026-11-20, challenger 검토 반영 · 팀장 결정)
- 쓰기 허용(최종): `apps/api/app/production/ai_draft*.py` · `apps/api/app/routes/production_ai.py` · `supabase/migrations/20261120000022_ai_draft_variety.sql`(reserve_ai_draft 교체만) · `supabase/tests/production_ai_draft_test.sql` · `apps/api/tests/production/test_ai_draft*.py` · `apps/web/src/components/production/edit/variety-form.tsx`·`variety.test.tsx`(AiDraftButton 연결·고지 문구만) · `docs/04_API.md#A-14`.
- A1 SQL: reserve_ai_draft 조건을 `format not in ('category','variety')`로(shopping은 계속 거부, 048에서). variety이면서 job lang≠ko면 계수 없이 409.
- A2 variety 전용 assemble: 받는 필드는 header·cuts·subtitles·reactions뿐, lang·source_start_sec·preset_version은 서버 값. 그 밖의 키 0 테스트.
- A3 가짜 자막 금지(PRD S12): 현재 리비전에 사용자 대사가 없으면 도구 스키마에서 subtitles를 빼고 결과 []. 있으면 AI는 **사용자 대사 텍스트를 그대로** 출력 시각에 재배치만 할 수 있다 — 서버가 AI subtitles 텍스트 다중집합이 입력과 정확히 같은지 확인, 다르면 AI subtitles를 버리고 사용자 원래 자막 유지(팀장 결정).
- A4 프롬프트에 서버가 계산한 segment_len·원본 크기·띠 덮기 최소 scale·시트 시각(구간 0초 기준)과 "이모지·제어문자·3줄 이상 금지, 제목 60자 이하"를 넣는다.
- A5 사용자 대사는 `<untrusted_data>` JSON 안에만, 꺾쇠 이스케이프, 개수·길이 상한, 원문 로그 금지, 주입 테스트.
- A6 대사 전송 고지 문구(PRD#8 팀장 결정): 버튼 옆 "AI 초안을 만들면 입력한 대사·분석 시트·후보 제목이 Anthropic(Claude)으로 전송됩니다." 예능형 편집 패널에 AiDraftButton 연결.
