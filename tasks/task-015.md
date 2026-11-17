# task-015 MON-D2 관측 근거

| 항목 | 내용 |
|---|---|
| 웨이브 | W3 |
| 선행 | task-011, task-013, task-018 |
| 위험도 | 높음 |
| 보안 영향 | 노출 면 (비신뢰 값 렌더링) |
| 담당 | builder |
| 근거 | `spec MON-D2`, `docs/04_API.md#A-06`, `docs/01_PRD.md#9`, `design/wireframes/MON-D2.html`, `docs/design/Nomadroom_Dashboard_Design.html`(관측 근거 다이얼로그) |
| 쓰기 허용 | `apps/web/src/components/evidence/**`, `apps/web/src/app/api/evidence/**`, `apps/web/src/server/api/monitor.ts`(getEvidence 추가), `apps/web/src/components/monitoring/monitor-view.tsx`(버튼 교체만) |

## 할 것
- `spec MON-D2` 구성 블록·상태·다음 화면대로 이전·현재 관측값, 증가율, 판정 reason 코드의 한국어 문구, 근거 대기(`needs_prev`)·다음 관측 시각(KST).
- reason 코드→문구 표는 PRD#9 코드 그대로(새 코드 추가 금지).

## 하지 않을 것
- 추세 차트·알림(이후), 판정 로직 재계산(서버 값만 표시).
- 셸 재구현 금지(task-018 사용).

## 완료 조건 (실행 가능한 확인)
- [x] `pnpm typecheck && pnpm lint && pnpm test` 통과(근거 대기·제외·제작 가능·404 상태)
- [x] reason 코드 10종 전부 문구 매핑 테스트 통과
- [x] `shot`으로 3구간 캡처 확인

## 착수 결정 (팀장, 2026-11-17 challenger 반영)
- 화면은 spec대로 /monitor 다이얼로그. `monitoring/[id]` 경로는 만들지 않는다(쓰기 허용 정정).
- 렌더 조합: curr null(대표 판정 없음) → "아직 관측 기록이 없습니다" + 다음 관측 시각. needs_prev && curr → "이전 관측값 필요" + 현재만. prev·curr 모두 → 표 2행 + 증가율. status=pending·license_unknown은 표+증가율+사유 문구.
- reason: 10종 밖 값은 Route Handler에서 null로 낮춘다. null이면 사유 줄 생략(producible은 "허용 증가율 안"). 제외 후보는 사유 문구를 증가율보다 먼저.
- 다음 관측 시각이 지났으면 "관측 가능(기록 검증 실행 시 반영)".
- 401 → SESSION_EXPIRED_PATH 이동, 404 → 닫기 + router.refresh(). 닫기·id 변경 시 이전 요청 abort, 재시도 중 버튼 잠금.
- 순수 뷰(상태 prop) + fetch 컨테이너 분리. shot은 팀장이 Playwright로 버튼 클릭 후 캡처.

## 리뷰 반영 결정
- reviewer(code·security) ACCEPT. 🟡 반영: 관측 없음·이전 관측값 필요 분기에도 사유 표시, 404/403 고정 문구(NOT_FOUND·FORBIDDEN), 로딩 aria 중복 제거.
- 클라이언트는 server-only client.ts를 못 읽어 세션 정리 경로 상수를 evidence.ts에 복제(같은 값 테스트로 고정).
- 3구간 캡처: CDP 스크립트(scratchpad). Docker 실행 후 Windows가 9327~9526 포트를 예약하므로 디버그 포트는 19335.
