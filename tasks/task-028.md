# task-028 P0 인수 테스트 CAT-01~07

| 항목 | 내용 |
|---|---|
| 웨이브 | W4 |
| 선행 | task-024, task-026, task-027 |
| 위험도 | 보통 |
| 보안 영향 | 없음 |
| 담당 | tester |
| 근거 | `docs/01_PRD.md#2`(S7~S9), `Nomadroom_Category_Shorts_PRD.md#5`(인수 기준), `docs/02b_PRODUCTION_FLOW.md` |
| 쓰기 허용 | `apps/api/tests/production/acceptance/**`, `apps/worker/tests/production/acceptance/**`, `apps/web/src/**/*.test.ts(x)`(제작 화면 테스트만), `tasks/NOW.md` |

## 할 것
- CAT-01(후보→제작 시작)~CAT-07을 기획서 #5 기준으로 실행 가능한 시나리오로 작성: 업로드→prepare→편집안→승인→렌더→ffprobe 검증→검수 승인.
- task-021 리뷰 🟡1: 배포본 validate 동등성 테스트를 강화한다(오류 코드 비교, hook 빈 값·NaN·헤더 줄 수·items y 케이스).
- 실영상 짧은 샘플(저장소 밖 경로·환경변수)로 로컬 워커 실렌더 1건.

## 하지 않을 것
- 제품 코드 수정(실패는 보고만), P1 항목(CAT-08), 실서비스 데이터 사용.

## 완료 조건 (실행 가능한 확인)
- [ ] `cd apps/api && pytest -q tests/production` · `cd apps/worker && pytest -q tests/production` · `pnpm test` 통과
- [ ] 실렌더 산출물 `ffprobe -v error -show_entries stream=width,height,r_frame_rate,codec_name` 이 608×1080·30fps·h264/aac
- [ ] CAT-01~07별 통과 표를 `NOW.md`에 기록

## 구현 결정 (2026-11-19, tester)
- 테스트 구성: API `tests/production/acceptance/`(CAT-01~07 시간순 시나리오 18건 + 배포본 validate 동등성 30건, 가짜 PostgREST·Storage는 ProdDB 재사용), 워커 `tests/production/acceptance/`(CAT-02·04·05·06·07 + validate 오류 메시지 고정 29건, 가짜 API + 실제 ffmpeg), 웹 `components/production/cat-acceptance.test.tsx`(화면·요청, 결함 재현 2건은 `it.fails`).
- 샘플(저작물 없음): ffmpeg lavfi `testsrc2=1280x720@30 50초 + sine 440Hz`(실환경), 훅 `sine 660Hz` 1.0초(정상)·3.0초(hook_too_long). 워커 테스트는 파랑 30초+빨강 12초 합성(구간 시작 30초 검증)·무음·가장자리 흰 피사체 합성.
- 실환경(로컬 Supabase + FastAPI `python -m app` 포트 8028 + 워커 `main.py`)은 scratchpad `acc028/e2e_real.py`가 사용자·워크스페이스·워커 토큰을 만들고 끝나면 지운다(키는 `supabase status -o env`를 메모리로만). 웹 화면은 거치지 않고 사용자 JWT로 사용자 API를 직접 호출했다.
- 동등성: 배포본 ValueError 메시지를 기대값으로 고정(배포본 import 없음). 의도된 차이 — 우리는 오류를 모아 반환, 훅 문구 항상 필수·`hook.audio_xor`, P0는 lang ko만.
- CAT-05 소리 검증은 ffmpeg volumedetect(훅 구간·훅 이후 구간 평균 음량)으로 한다. 원본 소리 복귀 > -45dB, 무음 원본 < -70dB.
- 발견(제품 코드 미수정, `it.fails`로 재현): (1) CAT-04 훅이 길 때 필요한 초 안내가 화면·실패 보고에 없다. (2) CAT-06 PROD-03에 글자 잘림·검은 틈·피사체 잘림 검수 안내가 없다(docs/03에도 항목 없음). 알려진 한계: 가로 원본은 중앙 크롭이라 가장자리 피사체는 잘리고 자동 탐지가 없다(리포트 review_required로 사람 검수).
