# task-048 AI 대본 3안 + 게시 문구 초안

| 항목 | 내용 |
|---|---|
| 웨이브 | W9 |
| 선행 | task-047, task-029 |
| 위험도 | 높음 |
| 보안 영향 | 외부 계약(Claude) · brief 텍스트 외부 전송 |
| 담당 | builder + tester |
| 근거 | `docs/04_API.md` A-14·A-21, `docs/research/shopping-shorts-notion-analysis.md#3` |
| 쓰기 허용 | `apps/api/app/production/ai_*.py`, `apps/api/tests/production/test_ai_shopping.py` |

## 할 것
- 노션 프롬프트 규칙으로 후킹이 다른 3안·글자 수·후킹 유형·확인할 사실 목록. 게시 문구 초안(대가성 표기 첫 줄·댓글 키워드). 출력은 서버 검증 후 저장. 호출 상한 Q7 공용.

## 하지 않을 것
- 확인 안 된 효능·가격 생성 허용, 키를 웹·워커에 두기.

## 완료 조건 (실행 가능한 확인)
- [ ] `pytest -q tests/production/test_ai_shopping.py` 통과(모의 응답: 정상·[확인 필요]·스키마 위반)

## 착수 결정 (팀장 2026-11-20, challenger REVISE 반영)
- S1 쓰기 허용 확장: `supabase/migrations/20261120000025_ai_draft_shopping.sql`, `apps/api/app/routes/production_ai.py`, `apps/api/app/production/ai_draft_shopping.py`, `docs/04_API.md`(A-14 행만), shopping 거부를 단정하던 기존 테스트(`apps/api/tests/production/test_ai_draft.py`·`test_ai_draft_variety.py`·`supabase/tests/*production_ai_draft*`), 새 `apps/api/tests/production/test_ai_shopping.py`·pgTAP. `validation_shopping.py`·spec 스키마·웹은 바꾸지 않는다. 웹 3안 선택 UI·brief 전송 화면 고지는 후속 task-056.
- S2 입력: brief 전 필드(상품명·불편·facts·avoid / 여행지·상품 유형·소구점)·target·comment_keyword·vertical만. 이미지·시트·analysis·원본·음성은 보내지 않는다. 쇼핑은 ko 작업만(lang≠ko는 409, 계수 없음 — RPC에서 검사).
- S3 출력(tool 스키마): variants[3]{hook_type enum 6종(손실 회피·정체성 자극·궁금증 유발·희소성·감정 공감·B급 유머), sentences[4]}, facts_to_check[](상한 있음). caption 초안은 만들지 않는다 — 게시 문구는 A-21 서버 고정 문구(대가성 첫 줄·댓글 키워드)가 정본.
- S4 서버 검증(위반 시 재시도 1회 후 502): 3안 hook_type 서로 다름 · 각 4문장 · 문장당 길이 상한 · has_banned(금지 품목) 또는 brief.avoid 문구 포함 시 위반. 글자 수는 서버가 센다(기존 validation 규칙과 같은 방식).
- S4b `[확인 필요]` 표기(3안 모두): AI가 쓴 표기 변형(`[확인필요]`·`【확인 필요】` 등)은 지우고 서버가 문장 **맨 앞**에 정확한 `[확인 필요] `를 붙인다. 대상 = NFKC 후 숫자 토큰(숫자+단위) 또는 한글 수량·가격·효능어(배·반값·절반·최저가·할인·무료·효과·효능·개선·완화 등 목록 상수)를 포함하고, 그 토큰이 brief(facts 포함) 텍스트에 **같은 토큰으로** 없는 문장. 판정 목록은 모듈 상수로 두고 테스트로 고정.
- S5 저장: 새 리비전(origin=ai_draft, 미승인) 1개 — 직전 리비전 spec을 그대로 상속하고 `script`만 1안으로 교체(cuts·voice·cta·disclosure·masks 유지). 3안·hook_type·글자 수·facts_to_check는 spec 밖, AI 초안 요청 행(000018 테이블)에 새 jsonb 열로 저장하고 A-14 응답(`variants`, 멱등 replay 때도 같은 값)으로 돌려준다 → 워커·렌더 페이로드에 안 감. 검증은 `_shopping_assets` 자산 맵을 넘겨 호출. 문장별 녹음이 이미 있으면 응답 notes에 `voice.narration_stale` 안내.
- S6 마이그레이션: reserve_ai_draft는 **000022 본문**을 복사해 교체(variety·ko 검사 유지)하고 shopping+ko 허용, revoke/grant 재선언. 적용된 마이그레이션 수정 금지.
- 검증: 워커 opus, 변경 후 codex-reviewer(code)+reviewer(security/contract).

## 구현 결정 (builder 2026-11-20)
- 3안 저장 위치: 000018의 "요청 행"은 테이블이 아니라 `production_jobs.ai_draft_requests` jsonb 원소다. 새 열 대신 그 원소에 `variants`·`facts_to_check` 키로 저장(스키마 변경 없음). `_ai_draft_json`이 두 키를 돌려주고 A-14 응답 `variants`·`facts_to_check`(쇼핑 외 null).
- 000025: `create_ai_draft_revision` 6인자를 drop 후 `p_variants`·`p_facts`(기본 null) 8인자로 재생성(기본값 오버로드 공존 시 PostgREST 이름 호출 모호). 본문은 000018 그대로 + 저장, 배열 아닌 값은 22023. reserve는 000022 본문 + shopping(ko) 허용·ja는 NR010.
- 검증 상수(`ai_draft_shopping.py`): 문장당 70자(가정), facts_to_check 10개·200자. avoid는 `, ， 、 ; / 줄바꿈`으로 나눠 정규화 2자 이상 문구를 포함 검사. 금지 품목은 문장·facts 모두 `has_banned`.
- [확인 필요]: 숫자 토큰 = NFKC·casefold 후 숫자(쉼표 제거)+단위 목록(`NUMBER_UNITS`), 수량·가격·효능어 = `CLAIM_WORDS`(공백 제거 부분 문자열, '배'는 숫자 단위·두배 등으로만). 비교 원문은 brief의 product_name·pain·facts·destination·product_type·appeal(avoid·target 제외). 표기 변형(괄호 종류·공백 무관)은 지우고 맨 앞에 `[확인 필요] `. `char_count`는 표기를 뺀 공백 포함 글자 수 합.
- 직전 리비전 spec이 없으면 DraftFailed(no_base) → 502(예약은 이미 계수됨). 1안의 `[확인 필요]`는 편집안 검증 `script.unverified` 오류로 저장(승인 전 사람이 지움).
- (리뷰 반영 🔴) 한글 수 표기(`KO_NUMBER_WORDS` 한·두·세…열·십·백·천·만·억 + `KO_NUMBER_UNITS` 배·원·개·%·퍼센트·번·분·초 등, 띄어쓰기 허용, 한글 뒤에 붙은 것 제외)도 숫자 토큰으로 보고 공백 제거 토큰('다섯배'·'백원')이 brief에 없으면 `[확인 필요]`.
- (리뷰 반영 🟡) 3안 각 문장은 `validation_shopping._multi_sentence`와 같은 판정으로 1문장이어야 하고, 위반은 재시도 후 502.
- (리뷰 반영 🟡) 광고·협찬 부인 문구(`AD_DENIALS`: 광고 아님·광고 아니·협찬 없·내돈내산·돈 안 받 등, 정규화 부분 문자열) 포함 시 위반 → 재시도 후 502.
