# task-015 MON-D2 관측 근거

| 항목 | 내용 |
|---|---|
| 웨이브 | W3 |
| 선행 | task-011, task-013 |
| 위험도 | 높음 |
| 보안 영향 | 노출 면 (비신뢰 값 렌더링) |
| 담당 | builder |
| 근거 | `spec MON-D2`, `docs/04_API.md#A-06`, `docs/01_PRD.md#9`, `design/wireframes/MON-D2.html` |
| 쓰기 허용 | `apps/web/src/app/(dashboard)/monitoring/[id]/**`, `apps/web/src/components/evidence/**`, `apps/web/src/app/api/evidence/**` |

## 할 것
- `spec MON-D2` 구성 블록·상태·다음 화면대로 이전·현재 관측값, 증가율, 판정 reason 코드의 한국어 문구, 근거 대기(`needs_prev`)·다음 관측 시각(KST).
- reason 코드→문구 표는 PRD#9 코드 그대로(새 코드 추가 금지).

## 하지 않을 것
- 추세 차트·알림(이후), 판정 로직 재계산(서버 값만 표시).

## 완료 조건 (실행 가능한 확인)
- [ ] `pnpm typecheck && pnpm lint && pnpm test` 통과(근거 대기·제외·제작 가능·404 상태)
- [ ] reason 코드 10종 전부 문구 매핑 테스트 통과
- [ ] `shot`으로 3구간 캡처 확인
