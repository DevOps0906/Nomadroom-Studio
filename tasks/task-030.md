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
