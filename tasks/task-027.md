# task-027 PROD-03 작업·검수 화면

| 항목 | 내용 |
|---|---|
| 웨이브 | W4 |
| 선행 | task-023, task-025 |
| 위험도 | 보통 |
| 보안 영향 | 없음(MP4·리포트는 서명 GET, 실패 사유는 이스케이프) |
| 담당 | builder |
| 근거 | `spec PROD-03`, `docs/03_SCREENS_UX.md`, `docs/04_API.md#A-09`(GET)·`#A-15`~`#A-18`, `docs/02b_PRODUCTION_FLOW.md`(상태) |
| 쓰기 허용 | `apps/web/src/app/(dashboard)/production/[id]/page.tsx`, `apps/web/src/components/production/run/**`, `apps/web/src/app/api/production-jobs/[id]/render-runs/**`, `apps/web/src/app/api/production-jobs/[id]/assets/**`, `apps/web/src/app/api/production-jobs/[id]/review/**` |

## 할 것
- 진행·단계·실패 사유 표시(폴링), "렌더 요청"(승인됨·렌더 미시작 문구, 요청 중 비활성), 실패 때만 "재시도", `hook_too_long`·`text_too_long`은 "편집안으로 돌아가 고치기" 링크.
- 검수 대기: MP4 재생·리포트·다운로드(A-18)·"검수 승인 → 완료"(A-17). 워커 오프라인 안내.

## 하지 않을 것
- 편집안 수정 UI, 서버 상태 전이 로직 변경, 서명 URL 저장·로그.

## 완료 조건 (실행 가능한 확인)
- [ ] `pnpm typecheck && pnpm lint && pnpm test` 통과(상태별 버튼 노출·실패 사유별 링크·타 Origin 403)
- [ ] hex·px 직접 사용 0건(`grep -rnE "#[0-9a-fA-F]{6}|[0-9]px" apps/web/src/components/production/run`)
