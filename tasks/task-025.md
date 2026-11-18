# task-025 PROD-00·PROD-01 화면 + MON-01 카테고리형 제작 버튼

| 항목 | 내용 |
|---|---|
| 웨이브 | W4 |
| 선행 | task-022 |
| 위험도 | 보통 |
| 보안 영향 | 없음(업로드 PUT은 서명 URL, 외부 입력은 이스케이프) |
| 담당 | builder |
| 근거 | `spec PROD-00`, `spec PROD-01`, `spec MON-01`, `docs/03_SCREENS_UX.md`, `docs/04_API.md#A-09`·`#A-10`·`#A-11` |
| 쓰기 허용 | `apps/web/src/app/(dashboard)/production/page.tsx`, `apps/web/src/app/(dashboard)/production/new/**`, `apps/web/src/app/(dashboard)/production/[id]/source/**`, `apps/web/src/components/production/**`, `apps/web/src/app/api/production-jobs/**`, `apps/web/src/components/monitoring/monitor-view.tsx`(버튼 배치만), `apps/web/src/components/shell/nav-config.ts`(필요 시 라벨만) |

## 할 것
- PROD-00 작업 목록(상태·빈 상태 "소재수집 열기"·"새 작업"), PROD-01 원본 업로드(서명 PUT)·구간·출처·"사용 권한 확인" 체크, 준비 완료 시 "편집안으로".
- MON-01 "내부 제작" 버튼(W4에서는 PROD-01이 카테고리형만, 형식 선택은 task-037)(CAT-01: 후보 ID·제목·원본 URL·라이선스 전달). 기존 "영상 만들기 →" 유지.
- 반응형 3구간, 색·크기 토큰만, 모든 Route Handler 첫 줄 `assertSameOrigin`.

## 하지 않을 것
- PROD-02·PROD-03, URL 원본 입력 활성화(031), 서버 로직·API 변경, 외부 링크 사이드바 항목 변경.

## 완료 조건 (실행 가능한 확인)
- [ ] `pnpm typecheck && pnpm lint && pnpm test` 통과(상태별 렌더·타 Origin 403 테스트 포함)
- [ ] hex·px 직접 사용 0건(`grep -rnE "#[0-9a-fA-F]{6}|[0-9]px" apps/web/src/components/production`)
