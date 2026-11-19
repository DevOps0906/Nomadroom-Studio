# task-033 P1 인수 테스트 CAT-08 + 회귀

| 항목 | 내용 |
|---|---|
| 웨이브 | W5 |
| 선행 | task-029, task-030, task-031, task-032 |
| 위험도 | 보통 |
| 보안 영향 | 없음 |
| 담당 | tester |
| 근거 | `docs/01_PRD.md#2`(S10), `Nomadroom_Category_Shorts_PRD.md#5`(CAT-08), `docs/02b_PRODUCTION_FLOW.md` |
| 쓰기 허용 | `apps/api/tests/production/acceptance/**`, `apps/worker/tests/production/acceptance/**`, `apps/web/src/**/*.test.ts(x)`(제작 화면 테스트만), `tasks/NOW.md` |

## 할 것
- CAT-08(P1 통합: AI 초안·TTS·URL 원본·오버레이 포함 1건 종단)과 P0 CAT-01~07 회귀. TTS 실패 시 첨부 음성 복귀 경로 확인.

## 하지 않을 것
- 제품 코드 수정(실패는 보고만), P2·후속 범위.

## 완료 조건 (실행 가능한 확인)
- [ ] `cd apps/api && pytest -q` · `cd apps/worker && pytest -q` · `pnpm typecheck && pnpm lint && pnpm test` 전체 통과
- [ ] 종단 산출물 `ffprobe` 608×1080·30fps·h264/aac
- [ ] `supabase test db` 통과 · CAT-01~08 통과 표를 `NOW.md`에 기록

## 구현 결정 (2026-11-19, tester)
- 추가 테스트: API `acceptance/test_cat08_acceptance.py`(23)·`test_cat08_ai_draft_acceptance.py`(4) · 워커 `acceptance/test_cat08_worker_acceptance.py`(10, 실제 ffmpeg 프레임 비교) · 웹 `components/production/cat08-acceptance.test.tsx`(9). 결과 api 975+13 integration · worker 246 · web 433 · supabase db reset 후 test db 432 통과.
- 실환경(scratchpad `acc033/e2e_cat08.py`, 워커 래퍼 `worker_mock.py`): Claude=로컬 HTTP 서버+`ANTHROPIC_BASE_URL`·가짜 키(제품 코드 무수정), edge-tts·yt-dlp=워커 래퍼가 `production.tts.edge_save`·`runner.fetch_url` 대체(실제 `check_url`은 유지). 흐름 A: URL→prepare→AI 초안→오버레이+TTS→tts_failed(review 복귀)→첨부 음성 새 리비전→재승인→렌더→done / B: TTS 성공+오버레이. P0는 acc028 `e2e_real.py` 재실행 통과.
- 결함 후보(🟡, 제품 미수정, 재현=it.fails/xfail strict): (1) 편집 화면에 TTS voice·rate 선택 UI 없음(AI 초안 새 작업은 hook.audio_xor 오류로 시작, 첨부 업로드 외 해결 수단 없음) (2) tts_failed·hook_too_long·text_too_long 후 job=review인데 RunView는 job.status==="failed"일 때만 사유·"편집안으로 돌아가 고치기"를 보임(기존 CAT-04 웹 테스트는 status failed로 가정) (3) 제목(header)을 가리는 오버레이는 경고 없음(실프레임 확인) (4) AI 초안 새 리비전은 직전 overlays를 옮기지 않음(설계 결정 필요).
