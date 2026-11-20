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
