# task-043 쇼핑 편집안 검증

| 항목 | 내용 |
|---|---|
| 웨이브 | W8 |
| 선행 | task-042 |
| 위험도 | 보통 |
| 보안 영향 | 없음(순수 검증) |
| 담당 | builder + tester |
| 근거 | `docs/05_DATA_MODEL.md` 쇼핑 spec 표, `tasks/plan-shopping-japanese.md#팀장 설계 결정` |
| 쓰기 허용 | `apps/api/app/production/validation_shopping.py`, `validation.py`(분기만), `apps/api/tests/production/test_validation_shopping.py` |

## 할 것
- script 정확히 4문장(오류)·110~140자(경고)·`[확인 필요]`(오류)·금지 문구·1번 제품명(경고). cuts 다중 원본·문장 매핑(문장마다 1개 이상)·masks 범위·빈 화면. voice 둘 중 하나(narration은 kind `narration`만). `image` 컷·`motion`(pan·zoom·none, `cuts.motion_invalid`), AI 생성 컷 미검수 `gen.unreviewed`. 권리 승인 조건(basis 전부·초상 동의).

## 하지 않을 것
- 일반쇼츠 검증 변경, 렌더러.

## 완료 조건 (실행 가능한 확인)
- [ ] `cd apps/api && pytest -q tests/production/test_validation_shopping.py` 통과
- [ ] `pytest -q tests/production` 회귀 통과

## 구현 결정 (2026-11-20, builder)
- 진입점 `validate_shopping_spec(raw, *, assets=None, job_lang=None, product_name=None, banned_phrases=기본 3개)`. `validation.py`는 없어 `validation_variety.validate_for_format`에 shopping 분기만 추가(순환 import 회피 지연 import 포함 4줄, `job_lang`만 전달 → 자산 검사 없음). 자산 검사가 필요한 API(044)는 `validate_shopping_spec`을 직접 호출한다.
- `assets`는 호출자가 이 작업 소유 행만 담은 id → {kind, status, duration_sec, width, height, rights, reviewed}. None이면 source_invalid·원본 길이·motion 종류·voice 자산·권리·gen·bgm 자산 검사를 생략한다(스키마·대본·문장 매핑·masks·빈 화면(1080x1920 가정)은 항상 수행).
- 추가 코드(표에 없음): `script.empty_text`·`cuts.count`·`cuts.scale`·`cuts.sentence_invalid`(1~4 밖)·`bgm.asset_invalid`·`path.forbidden`·`lang.mismatch`. 스키마 오류는 `schema.*`로 의미 검사 생략(기존과 동일).
- 빈 화면: 예능형과 같은 가로 맞춤 식을 전체 캔버스(0~1920) 기준으로 적용(가정). masks는 캔버스 좌표(w·h>0).
- 글자 수 경고는 대본이 4문장이고 lang≠ja일 때만. 권리 검사는 spec이 쓰는 원본·이미지·BGM만 대상(미사용 업로드 제외). 같은 자산은 첫 참조 경로에서 1회 보고, `rights.basis` 없으면 portrait·gen은 건너뜀. BGM basis 없음은 `bgm.rights_missing`.
- 금지어 기본값 "강력 추천"·"인생템"·"지금 바로"(금지어 설정 연동은 044 이후). `sources.few`는 컷의 서로 다른 source_asset_id 수 기준.

## 리뷰 반영 결정 (2026-11-20, 🔴 2건 + 팀장 결정)
- fail-closed: `validate_shopping_spec(assets=...)`는 기본값 없는 필수 인자. `validate_for_format`은 `assets` 인자를 받고 shopping에서 없으면 `assets.required` 오류를 반환한다. **task-044는 승인·저장 때 이 작업 소유 자산을 반드시 넘긴다**(다른 작업 id는 map에 넣지 않음).
- 컷 원본(source·source_upload·image)·BGM·narration 자산이 map에 없거나 `status`≠`ready`이면 각각 `cuts.source_invalid`·`bgm.asset_invalid`·`voice.asset_invalid`. 영상 컷 자산의 `duration_sec`이 null이면 `cuts.source_invalid`.
- `[확인 필요]`는 script·`cta.text`·`disclosure.text` 모두 검사(경로별 `script.unverified`).
- script 항목 1개 = 1문장: 항목 안 줄바꿈 또는 끝(연속 종결 부호 포함) 외 종결 부호(. ? ! 。 ？ ！)가 있으면 `script.multi_sentence`(URL·숫자 사이 마침표 숫자.숫자는 종결 부호로 세지 않음).
- `tts.rate`는 `[+-]\d{1,3}%` 문자열, `tts.voice`는 카테고리형 패턴(스키마 오류 `schema.string_pattern_mismatch`), voice lang 접두사≠spec lang이면 `voice.tts_lang`. `source_start_sec` 0~86400(스키마).
- 금지어는 공백 제거·casefold 후 부분 문자열 비교.
- `rights.basis=ai_generated` 자산은 `gen`(platform·model·request_id 비어 있지 않음, cost_krw 0 이상 정수) 없으면 `gen.missing`.
