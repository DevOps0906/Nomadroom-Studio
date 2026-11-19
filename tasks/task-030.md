# task-030 TTS (edge-tts, 워커 전용)

| 항목 | 내용 |
|---|---|
| 웨이브 | W5 |
| 선행 | task-028 |
| 위험도 | 높음 |
| 보안 영향 | 새 의존성(edge-tts) · 외부 서비스 아웃바운드 · 라이선스·이용 조건 |
| 담당 | builder |
| 근거 | `docs/01_PRD.md#7`(Q6), `docs/02b_PRODUCTION_FLOW.md`, `docs/04_API.md#W-07`(`hook_audio`) |
| 쓰기 허용 | `apps/worker/production/tts.py`, `apps/worker/tests/production/test_tts.py`, `apps/worker/pyproject.toml`·lock(의존성 추가만), `apps/web/src/components/production/edit/**`(TTS 선택 표시만) |

## 할 것
- 착수 조건: edge-tts `secscan license` 통과 + 이용 조건 확인 결과를 `docs/01_PRD.md#7` Q6에 팀장이 기록. 통과 못 하면 착수하지 않고 첨부 음성 경로 유지.
- 로컬 워커에서만 훅 음성 생성(→ `hook_audio` W-07 업로드). 실패·거부 시 첨부 음성 경로로 복귀하고 안내.

## 하지 않을 것
- API 서버·웹에서 TTS 실행, 무음·가짜 음성 대체, 라이선스 미확인 상태의 의존성 추가.

## 완료 조건 (실행 가능한 확인)
- [ ] `~/.claude/nomad/bin/secscan license` 통과(GPL·AGPL 0건), Q6 결과 기록됨
- [ ] `cd apps/worker && pytest -q tests/production/test_tts.py` 통과(TTS는 목: 성공 업로드, 실패 시 첨부 음성 유지·무음 생성 0건)
- [ ] 생성 음성 `ffprobe -v error -show_entries format=duration` 길이 출력, 훅 길이 규칙(W-09) 적용 확인

## 착수 결정 (2026-11-19, challenger 검토 반영 · 팀장 결정)
- Q6 결과는 `docs/01_PRD.md#7` Q6·Q14 행에 기록됨(LGPL-3.0 수용, 이용 조건 미확인 → 기본 꺼짐 `WORKER_TTS_ENABLED`).
- 쓰기 허용 추가: `apps/worker/production/adapter.py`·`runner.py`·`config.py` · `apps/worker/uv.lock` · `apps/worker/tests/production/test_runner.py` · `apps/api/app/routes/worker_production.py`(RenderCode에 tts_failed만) · `supabase/migrations/*000020*.sql`(job 전이·A-16 거부 목록에 tts_failed가 SQL에 있으면 그 함수 교체만, 필요 없으면 만들지 않음) · `apps/web/src/components/production/run/model.ts`(REASON_TEXT·EDIT_FIRST_CODES만) · `docs/04_API.md`(W-09·A-16). `.env*`는 에이전트 권한 밖 — 새 변수 이름은 구현 결정에 적어 사람이 추가.
- I1 실패 계약: TTS 실패는 `tts_failed`(stage=audio). hook_too_long·text_too_long처럼 review 복귀·A-16 재시도 거부·웹 "편집안으로 돌아가 고치기"(첨부 음성으로 바꿔 재승인). 첨부로 자동 대체하지 않는다(승인본과 다른 음성 금지).
- I2 TTS 꺼짐인데 spec.hook.tts면 `tts_failed`(detail에 비활성 표시), 웹 TTS 선택 옆에 "워커 설정에서 TTS가 꺼져 있으면 실패합니다" 안내. 상태 노출 API는 만들지 않는다.
- I3 spec.hook.tts가 있으면 W-06 hook_audio를 쓰지 않고 TTS만. 생성 음성은 make_hook로 정리·실측한 wav를 W-07 hook_audio로 올리고 check_hook를 그대로 거친다. report.json tts 칸에 실제 경로(voice·rate 또는 supplied recording).
- I4 edge-tts==7.3.1 고정. Communicate에 connect·receive 타임아웃 + asyncio.wait_for 전체 상한, 시작 전후 cancel.check(). 외부로 나가는 것은 hook.text·voice·rate뿐. 문구·voice 로그 금지, edge_tts·aiohttp 로거 WARNING, 예외는 type 이름만. voice·rate ValueError → tts_failed.
- I5 검증: pytest는 목으로 성공·실패·꺼짐·중단 4경우. 실제 edge-tts 호출 스모크는 이용 조건 미확인이라 에이전트가 하지 않는다(사용자가 켜고 직접 확인). ffprobe 길이는 목이 만든 합성 mp3로 확인.
- 순서: task-032(adapter·render 수정 중) 커밋 뒤 착수, 그 다음 task-031.

## 구현 결정 (2026-11-19, builder)
- 설정: `production/config.py` `TtsSettings`(env_prefix `WORKER_TTS_`, 필수 값 없음). runner가 인자 없으면 직접 읽어 `main.py`는 바꾸지 않음. 사람이 `.env.example`에 추가할 이름: `WORKER_TTS_ENABLED`(기본 false) · `WORKER_TTS_TIMEOUT_SEC`(전체 상한, 기본 90) · `WORKER_TTS_CONNECT_TIMEOUT_SEC`(10) · `WORKER_TTS_RECEIVE_TIMEOUT_SEC`(30).
- `production/tts.py`: `synthesize`가 꺼짐·voice/rate 형식 오류·예외·타임아웃·빈 파일을 모두 `TtsFailed`(audio/tts_failed, detail은 예외 종류 이름만)로. rate 없으면 `+50%`(05_DATA_MODEL). 409 중단은 0.2초 간격으로 확인해 합성 task를 취소하고 `TaskCancelled`. edge_tts는 켜졌을 때만 import.
- runner: spec.hook.tts면 W-06 hook_audio를 받지 않음 → TTS mp3 → `make_hook`(정리·실측 wav, 무음·형식 오류는 tts_failed) → `check_hook` 그대로 → W-07 hook_audio 업로드. report `tts`=`edge-tts voice=… rate=…`, `hook_audio_asset_id`=null.
- DB: `20261119000020_production_tts_failed.sql`(retry_render_run·finish_production_task 코드 목록에 tts_failed만 추가) + pgTAP `supabase/tests/production_tts_failed_test.sql`. 미실행(팀장이 순서 잡아 실행).
- 범위 밖 수정 1건: `tests/production/test_units.py`의 "TTS 훅 → AudioMissing" 테스트를 새 동작(문구 매핑)으로 바꿈.
- 리뷰 반영(security): voice는 `[a-z]{2,3}-[A-Z]{2,4}-[A-Za-z0-9]+Neural`, rate는 `[+-]\d{1,3}%`로 fullmatch(edge-tts가 SSML에 이스케이프 없이 넣음·끝 개행 거부). 워커 `tts.py`(불일치 tts_failed, 합성 전)와 API `spec.py` Tts 모델(검증 오류로 승인 차단)이 같은 패턴. 네트워크: edge-tts는 aiohttp `trust_env=True`라 운영자 PC 프록시 설정(HTTPS_PROXY 등)을 따른다. 대상 호스트는 라이브러리가 고정한 Microsoft 엔드포인트, TLS 검증 유지(certifi).
