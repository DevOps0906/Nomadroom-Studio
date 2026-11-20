# task-057 쇼핑 AI 영상 생성 견적·확인·검수 체크 UI

| 항목 | 내용 |
|---|---|
| 웨이브 | W9 |
| 선행 | task-054 |
| 위험도 | 보통 |
| 보안 영향 | 과금 확인 화면(owner만, 서버가 강제) |
| 담당 | builder |
| 근거 | `docs/04_API.md` 55행(A-22), `tasks/task-054.md#착수 결정 G1·G4·G7`·`#구현 결정`, `docs/03_SCREENS_UX.md` 18·19·46행 |
| 쓰기 허용 | `apps/web/src/components/production/shopping/**`, `apps/web/src/server/api/production.ts`, `apps/web/src/app/api/production-jobs/[id]/generation-runs/**`(새 relay), `docs/03_SCREENS_UX.md`(PROD-01S·PROD-02S 행: 생성 위치 이동), 해당 테스트 |

## 착수 결정 (팀장)
- task-054 G1에 따라 AI 생성은 **PROD-01S(원본 단계, draft·failed(prepare))** 의 사진 행에서 한다(03_SCREENS_UX의 PROD-02S 위치를 PROD-01S로 정정). 흐름: 프롬프트·길이(1~15초) → 견적 보기(예상 비용·월/작업 잔액) → 확인 모달(owner 아니면 403 안내) → 진행 행(refresh 버튼·상태 quoted/confirmed/running/finalizing/done/failed/unknown 한국어 표기) → 결과 원본 행에 검수 체크 3항목(물리 오류·불가능 앵글·실제 사진 대조) → 모두 체크 시 review 호출.
- 서비스 꺼짐(503)·예산 0(409 budget_exceeded)이면 AI 생성 옵션을 숨기거나 "사용 안 함(예산 미설정)" 안내, 사진 모션은 그대로.
- PROD-02S는 `gen.unreviewed` 오류를 기존 오류 목록 방식으로 표시하고 PROD-01S로 가는 링크.

## 하지 않을 것
- API·DB 수정, 자동 폴링으로 과금 유발(refresh는 수동 버튼 또는 숨김 탭 정지 폴링), 프롬프트·URL 로그.

## 완료 조건 (실행 가능한 확인)
- [ ] `cd apps/web && pnpm lint && pnpm typecheck && pnpm test` 통과(relay 5개 경로·견적→확인 모달·403/409/503 표시·검수 3항목 모두 체크해야 호출 테스트)
