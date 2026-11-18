# task-046 화면: 유형 선택·PROD-01S·PROD-02S·게시 문구

| 항목 | 내용 |
|---|---|
| 웨이브 | W8 |
| 선행 | task-044 |
| 위험도 | 보통 |
| 보안 영향 | 없음 |
| 담당 | builder |
| 근거 | spec `PROD-00`·`PROD-01S`·`PROD-02S`·`PROD-03`(`design/spec.json`), `docs/03_SCREENS_UX.md` |
| 쓰기 허용 | `apps/web/src/app/(app)/production/**`, `apps/web/src/components/production/**`, 해당 테스트 |

## 할 것
- "내부 제작" → 유형 → 형식/분야. PROD-01S 원본 다건·권리·brief·제휴 링크·경고. PROD-02S 4문장(카운터)·문장별 컷·마스크·음성·CTA·표기. PROD-03 게시 문구 복사·권리 목록. 반응형 3구간.

## 하지 않을 것
- 일반쇼츠 화면 동작 변경, API 변경.

## 완료 조건 (실행 가능한 확인)
- [ ] `corepack pnpm --dir apps/web test`·`lint`·`typecheck` 통과
- [ ] 3구간 캡처 확인
