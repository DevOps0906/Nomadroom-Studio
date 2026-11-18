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
