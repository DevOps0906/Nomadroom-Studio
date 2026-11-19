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

## 구현 결정
- 목록(PROD-00)은 서버 컴포넌트 + Suspense(스켈레톤), 상태 필터·페이지는 쿼리(`status`·`page`, 20건). 열은 제목·형식·상태(+실패 단계·코드)·수정 시각. 유형·언어·원본·최근 리비전 열과 검색·"제작 시작" 모달은 API 미구현(kind·lang·vertical·langs[], task-042·049) 또는 task-037 범위라 뺐다.
- PROD-01은 `/production/new`(생성 전)와 `/production/[id]/source`(생성 후) 같은 폼. "원본 준비 시작" = 생성 또는 PATCH → 업로드 서명(A-10) → 브라우저가 서명 URL로 PUT → complete → prepare(A-11). "저장"은 생성/PATCH만. 생성 키는 `createIntentKey`(본문 지문 단위, 전송 실패 시 유지).
- Route Handler 5개(`/api/production-jobs`, `[id]`, `[id]/uploads`, `[id]/uploads/[assetId]/complete`, `[id]/prepare`) 모두 첫 줄 `assertSameOrigin`, 응답은 id·status만(upload_url만 예외, no-store). 400·409·429는 API 문구 전달, 404는 일반 문구.
- 준비 중에는 3초마다 `router.refresh()`. 형식은 카테고리형 고정(예능형 옵션은 비활성 "준비 중"), URL 원본은 안내문만.
- MON-01 카드에 "내부 제작"(`/production/new?candidate_id&title&license`) 추가, "영상 만들기 →" 유지. 후보 원본 URL은 A-04 응답에 없어 전달하지 않았다.
- 미구현·후속: 출처 URL 입력(A-09에 필드 없음), 원본 미리보기 player(A-18 다운로드 URL 필요), 사이드바 "제작·업로드"는 외부 링크 항목이라 그대로(PROD-00 진입 링크는 팀장 결정).
- task-026·027이 /production/[id]·/production/[id]/edit 라우트를 만들 때까지 이 링크들은 임시 404다.
- 제목은 A-09 PATCH에 없어 작업 생성 후(또는 생성 직후) 읽기 전용으로 잠근다.
