# task-051 예능형 일본어 더빙

| 항목 | 내용 |
|---|---|
| 웨이브 | W10 |
| 선행 | task-050, task-038 |
| 위험도 | 높음 |
| 보안 영향 | TTS 의존 · 난이도 |
| 담당 | builder + tester |
| 근거 | `tasks/plan-shopping-japanese.md#팀장 설계 결정`(예능형 더빙) |
| 쓰기 허용 | `apps/worker/production/variety/**`(dub), 테스트 |

## 할 것
- 대사 자막별 ja TTS → 자막 구간 배치, 원본 duck(가정 15%), 넘치면 rate↑(상한 가정 +30%) 후 `dub_overflow` 경고.

## 하지 않을 것
- 원본 음성 완전 삭제 강제, 입모양 맞춤.

## 완료 조건 (실행 가능한 확인)
- [ ] `pytest -q tests/production/test_variety_dub.py` 통과(구간 안 배치·overflow 경고)

## 착수 결정 (팀장 2026-11-20, challenger REVISE 반영)
- D1 쓰기 허용(🔴1): `apps/worker/production/variety/**`, `adapter_variety.py`(LANGS에 ja), `runner.py`(variety ja 분기·tts 설정 전달·`result_{lang}.mp4`), `apps/api/app/routes/production_render.py`(variety+ja 409 해제)·해당 API 테스트, `docs/04_API.md` A-15 행·`docs/05_DATA_MODEL.md`(variety ja 더빙 메모), 테스트. variety 텍스트는 task-050 `pick_font(text, lang)`·JP 금칙을 **새로 연결**(제목도 JP Black).
- D2 목소리(🔴2, 사람 질문 → 팀장 기본값): spec은 바꾸지 않고 워커 상수 — 목소리 `ja-JP-NanamiNeural`, 기본 rate `+0%`. variety ja는 **녹음 대체 경로 없음**(TTS 전용, JA-04는 category·shopping만) — 문서에 명시.
- D3 더빙 대상(사람 질문 → 기본값): `subtitles[]` 중 대사 자막만(punch 강조·reactions는 더빙 안 함). 대사 수 상한 60(가정, 넘으면 `render_failed` 사유 기록).
- D4 배치·overflow 단일 규칙(🔴3): 시작 샘플 = `frame_of(start)×1600`(화면 자막 격자와 동일). 허용 창 = 다음 대사 자막 시작(마지막은 영상 끝)까지. TTS는 대사당 **1회만** 생성하고, 실측 길이가 창보다 길면 로컬 `atempo`로 최대 1.3배까지 빠르게; 그래도 길면 창 끝에서 30ms 페이드아웃으로 자르고 그 대사에 `dub_overflow`(report warnings, 대사 번호·초과 초).
- D5 소리(🟡2): 원본은 기존대로 loudnorm 후, 더빙 실제 구간(±50ms 페이드)에 PCM 이득 0.15로 duck, 그 위에 TTS 합성, 최종은 클리핑 방지 리미터만(믹스 뒤 loudnorm 없음). 원본 무음이면 TTS만.
- D6 실패(🟡4): TTS 일부라도 실패 → 전체 `tts_failed`. 워커 TTS 꺼짐 + 대사 ≥1 → `tts_failed`. 대사 0개 → 원본 그대로 + report warning `dub_none`. 시간 상한은 기존 렌더 DEADLINE 안에 TTS 포함.
- D7 표시(🟡5): report warnings(`dub_overflow`·`dub_none`)는 PROD-03 검수 리포트 카드가 표시(task-052에 반영 요청).
- D8 배포(🟡6): 새 capability 없이 "워커 먼저 배포"를 04_API에 명시(로컬 단일 운영자 환경). 완료 조건: `pytest -q tests/production/test_variety_dub.py`(구간 배치·atempo·overflow·duck 분산·dub_none·tts_failed) + 워커 tests/production 전체 + API pytest(variety ja 202).

## 구현 결정 (builder 2026-11-20)
- 워커: `production/variety/dub.py` 신설(`dub_lines`·`fit_clip`·`mix`·`build_dub`). `render_variety`가 `lang=ja`면 `_cut_audio` 뒤 더빙 믹스를 만들고 encoder는 `alimiter=limit=0.95:level=0`만(대사 0개면 기존 loudnorm 경로). TTS 시간은 `render_variety` 시작 기준 `DEADLINE_SEC` 안(호출마다 `min(남은 시간, WORKER_TTS_TIMEOUT_SEC)`).
- TTS 음성은 `hook_audio.make_hook`으로 앞뒤 무음을 정리한 실측 길이를 쓴다(그래서 배속은 원 음성 길이보다 약간 작을 수 있다). make_hook 실패(빈·무음)도 `tts_failed`.
- overflow 경고는 1.3배에 닿고도 넘칠 때만. 1.3배 미만 배속 뒤 몇 샘플 차이(반올림)는 경고 없이 자른다(자를 때는 항상 30ms 페이드).
- duck 구간은 페이드가 겹치는(간격 100ms 미만) 더빙끼리 한 구간으로 합친다(사이에서 원음이 튀지 않게). TTS 합성은 int16 포화 덧셈.
- report: `lang` 추가(ko 포함), ja만 `warnings[]{code, line?, overflow_sec?}`·`dub{tts, duck_gain, lines[]}`. `line`은 대사 자막 시작 순번(1부터, punch 제외) — 웹 `report-warnings/pick.ts` 키와 맞춤.
- 텍스트(D1): ja 제목 JP Black·대사/반응 JP Bold, 크기마다 `shopping.text.wrap_ja`(금칙)로 최대 3줄(순환 import라 함수 안 import). ko 경로 불변. 여러 줄 bbox 실수 → 정수 올림.
- API: A-15 variety+ja 409 제거(테스트 `test_task051_variety_ja_is_202`). 워커 테스트의 "variety ja 거부" 2건은 ja 허용·en 거부로 바꿈.
- 리뷰 반영(🟡3·문서1): 허용 창 0샘플(같은 시작 프레임·영상 끝 시작)은 TTS 전에 `render_failed`, 배치 수 = 대사 수 확인. TTS 음성 정리는 `dub._clean`(make_hook과 같은 TRIM)으로 바꿔 atempo·loudnorm과 함께 렌더 남은 시간 timeout, PCM 루프는 1초 분량마다 cancel·deadline 확인. ja 제목은 실제 높이로 위치 계산(`title_tops`: 겹치면 간격 8px로 412 중심에 쌓고 바닥 552 넘으면 올림, 맨 위가 0 위면 `text_too_long`). 04_API W-09에 variety ja `tts_failed`·`render_failed` 사유.
