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

## 구현 결정 (2026-11-20, builder)
- 000022: `reserve_ai_draft`만 `create or replace`(000018 본문 복사 + 형식 조건 교체, grant 재선언). 판정 순서: 같은 키 → 다른 작업 키 → review → `format not in (category, variety)` NR010 → variety·`lang`≠ko NR010 → 상한 → 60초. `production_jobs.lang` check가 아직 `ko`뿐이라 ja 분기는 방어용(pgTAP은 트랜잭션 안에서 check를 풀어 확인).
- 모듈: `ai_draft_variety.py`(프롬프트·도구 `submit_variety_draft`·입력 조립·assemble). `ai_draft.call_claude`에 `system`·`tool` 인자를 더해 공용(기본값은 카테고리형 그대로), 시트 이미지 블록은 `image_blocks`로 분리. 라우트는 `job.format == variety`면 `_draft_variety`, 재시도·실패 기록·502·로그 규칙은 카테고리형과 같다.
- 입력: ready JPEG 시트(생성 순 순번 = 워커 시트 페이지로 가정, 시트 i는 i×12 ~ i×12+11.5초), 현재 리비전 `subtitles` 중 text가 문자열인 항목, 후보 제목. analysis·원본·음성은 읽지 않는다. 대사는 `MAX_SUBTITLES`(200)개·`MAX_TEXT_CHARS`(200)자로 잘라 `<untrusted_data>` JSON(`dialogue` 배열)에 넣는다.
- 프롬프트 수치(A4): segment_len = min(작업 segment_len_sec, 원본 길이), 원본 크기(source_meta, 없으면 1080×1920 — 검증이 `source_size.missing`을 따로 낸다), 최소 scale = max(1, 816×W/(1080×H)) 소수 셋째 자리 올림, 덮기 조건 |x|≤(1080s−1080)/2·|y|≤(표시 높이−816)/2.
- 개수 상한은 검증 모듈 상수(컷 60·자막 200·반응 200)를 그대로 쓴다(config는 쓰기 범위 밖이라 새 설정값 없음). 초과는 형식 불일치로 재시도.
- A3: AI 자막 텍스트 다중집합(개수 포함)이 입력과 다르거나 subtitles가 없으면 사용자 원래 자막을 그대로 쓴다(시각이 새 컷 총길이를 넘으면 의미 오류로 저장되어 경로가 표시됨). 중첩 항목의 extra 키는 검증(extra=forbid)이 스키마 오류로 거부 → 재시도.
- 웹: 예능형 패널 하단 버튼 줄에 `AiDraftButton`(카테고리형과 같은 활성 조건) + 고지 문구 `AI_DRAFT_SEND_NOTICE`. 성공 시 새 리비전을 양식에 반영(applyDraft).

## 리뷰 반영 결정 (2026-11-20, code·security 🔴 없음)
- 1 시트 페이지: created_at·id 정렬(`order=created_at.asc,id.asc`, 경로에 페이지 없음, W-07 순차 업로드 전제). 제외 없이 순번(enumerate)을 페이지로 본다(카테고리형과 같은 조회). sheet_NNN 경로 파싱안은 경로에 페이지가 없어 시트 0장이 되는 회귀라 되돌렸다.
- 2 사용자 자막 폴백: AI 컷 총길이 기준 end>총길이면 end=총길이, start≥총길이인 자막만 제외. 텍스트는 바꾸지 않는다. 결과 메모를 `validation.warnings`에 덧붙임: `ai_draft.dialogue_kept`(subtitles) · `ai_draft.subtitle_trimmed`(subtitles.N) · `ai_draft.subtitle_dropped`(subtitles, 원래 번호는 문구에). 총길이를 계산할 수 없으면(숫자 아님) 손대지 않고 검증이 거부한다.
- 3 후보 제목은 `MAX_TEXT_CHARS`(200)자로 잘라 프롬프트에 넣는다(라우트 `_candidate_title`, 카테고리형·예능형 공통).
