# task-060 언어별 진행 상태(A-09 lang) + ja 녹음 업로드 화면

| 항목 | 내용 |
|---|---|
| 웨이브 | W11(안정화) |
| 선행 | task-052, task-058 |
| 위험도 | 보통(API 응답 확장·화면) |
| 보안 영향 | 없음 |
| 담당 | builder |
| 근거 | `tasks/README.md#발견한 문제` 2026-11-20 A-09 행, `docs/04_API.md` A-09·A-10 행, `tasks/task-052.md#구현 결정` |
| 쓰기 허용 | `apps/api/app/routes/production_jobs.py`(A-09 상세), API 테스트, `docs/04_API.md` A-09 행, `apps/web/src/components/production/**`, `apps/web/src/server/api/production.ts`, 웹 테스트 |

## 할 것
- A-09 상세에 언어별 최신 run(`latest_runs{ko, ja}`)과 자산의 렌더 언어(run lang) 노출 → PROD-03 ja 탭이 ja 진행률·MP4 재생·리포트를 구분.
- PROD-02·02S ja 탭에 녹음 업로드(category hook_audio, shopping narration 4개) → ja spec이 그 자산을 참조(JA-04 화면 경로).

## 하지 않을 것
- DB 스키마 변경, 기존 응답 필드 제거(추가만).

## 완료 조건
- [ ] api pytest·web lint·typecheck·test 통과

## 구현 결정 (builder 2026-11-20)
- API: `latest_runs`는 lang 필터로 언어별 최신 1건씩 조회, `render_lang`은 자산 `render_run_id` 목록으로 run lang 일괄 조회(건수 제한 없음, 못 찾으면 null). `latest_run`은 언어 무관 최신 1건 유지. `_upload_state_ok`: hook_audio는 inspect·done, narration은 done도 허용(ja 녹음, DB 트리거는 두 kind의 상태를 제한하지 않음 확인). 웹은 render_lang null을 ko로 단정하지 않는다.
- 웹 PROD-03: ko 탭은 `koDetail`(latest_run=ko run, ja 산출물 제외), ja 탭은 `runOfLang`·`assetOfLang`로 ja 진행률(폴링 4초)·MP4(Player 재사용)·리포트 선택. 구 API(latest_runs 없음)는 ko만 latest_run으로 본다.
- ja 음성(`lang/voice-model.ts`·`voice-panel.tsx`): category=hook_audio 1개(기존 `/revision/hook-audio` 흐름), shopping=narration 4칸(기존 `uploadAsset`, 권리 근거 선택), variety는 녹음 없음. 저장 때 `hook.audio_asset_id` 또는 `voice.narration_asset_ids`로 교체하고 TTS 값은 제거(둘 중 하나), TTS로 되돌리면 원래 tts(없으면 ja 기본)로 복원. 음성이 바뀐 때만 spec에 반영, 녹음 모드 불완전(4개 미만·중복)은 저장 버튼 차단. A-12 ja 저장은 기존 `base_updated_at` 경로 그대로.
- 가정: 이미 올린 다른 narration 자산 재선택 UI는 없음(업로드한 것만 연결). 서버 상태 규칙(hook_audio는 review·failed만 등)은 서버 409 문구를 그대로 보인다.
