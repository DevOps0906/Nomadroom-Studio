# task-055 W4·W5 인수 결함 보완(화면 안내·TTS 선택·오버레이)

| 항목 | 내용 |
|---|---|
| 웨이브 | W5 후속 |
| 선행 | task-033, task-037 |
| 위험도 | 보통 |
| 보안 영향 | 없음(화면 안내·검증 경고, 외부 호출 없음) |
| 담당 | builder |
| 근거 | `tasks/task-028.md#구현 결정`(발견 2건), `tasks/task-033.md#구현 결정`(결함 후보 4건), `docs/04_API.md#W-09`·`#A-14`, `docs/03_SCREENS_UX.md` PROD-02·PROD-03 |
| 쓰기 허용 | `apps/web/src/components/production/run/**` · `apps/web/src/components/production/edit/**`(TTS 선택 UI·안내만) · `apps/api/app/production/spec.py`(오버레이-제목 겹침 경고만) · `apps/api/app/production/ai_draft.py`(직전 overlays 이월만) · `apps/api/tests/production/**` · `apps/web/src/**/*.test.tsx` · `docs/03_SCREENS_UX.md`(PROD-03 검수 3항목) |

## 할 것
1. PROD-03: job이 review로 돌아왔고 최신 run이 failed(hook_too_long·text_too_long·tts_failed)면 실패 사유와 "편집안으로 돌아가 고치기"를 보인다(지금은 status=failed일 때만). hook_too_long이면 report·detail에 있는 값으로 필요한 초를 안내(없으면 W-09 식으로 계산 가능한 범위만).
2. PROD-03 검수 대기: 글자 잘림·검은 틈·핵심 피사체 잘림 확인 체크리스트(안내만), docs/03 PROD-03에 항목 추가.
3. PROD-02: 훅 음성 "첨부/TTS" 선택과 voice(허용 목록 드롭다운)·rate 입력 — 서버 패턴(voice `[a-z]{2,3}-[A-Z]{2,4}-…Neural`, rate `[+-]\d{1,3}%`)과 같게, "워커 설정에서 꺼져 있으면 실패" 안내 유지.
4. spec.py: 오버레이가 제목(header) 영역과 겹치면 경고(overlays.header_overlap).
5. ai_draft: 새 리비전에 직전 리비전의 overlays를 그대로 이월(팀장 결정: AI는 overlays를 만들지 않으며 사용자 입력 보존).
6. 위 항목의 기존 `it.fails`·`xfail(strict)` 재현 테스트를 정상 테스트로 바꾼다.

## 하지 않을 것
- 렌더러·워커·DB 변경, 실패 코드 추가, 외부 호출.

## 완료 조건 (실행 가능한 확인)
- [ ] `cd apps/api && uv run pytest -q` · `cd apps/web && pnpm typecheck && pnpm lint && pnpm test` 통과, it.fails·xfail 재현 테스트 0건 남음(해당 6항목)
- [ ] hex·px 0건(components/production)
