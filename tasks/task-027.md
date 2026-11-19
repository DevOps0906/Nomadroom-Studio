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

## 구현 결정
- 중계: `render-runs`(A-15, 키 정규식·ko만·revision_id UUID)·`render-runs/[runId]/retry`(A-16)·`review/approve`(A-17)는 첫 줄 assertSameOrigin, `assets/[assetId]/download-url`(A-18 GET)은 이 작업의 ready `output_mp4`·`report`만 연다(sheet 중계와 같은 방식). 응답은 id·status·attempt만, 전부 no-store.
- 산출물 선택: A-09 `assets[]`에 run 연결이 없어 가장 최근 ready `output_mp4`·`report`(생성순 마지막)를 쓴다. 재시도 run이 새 자산을 만들므로 최신이 현재 run 것이라는 가정.
- 렌더 요청 키: 리비전 id 지문의 의도 키(5xx·전송 실패는 유지, 4xx·성공은 교체). 재시도(A-16)는 키 없음.
- 폴링: 렌더 중·run queued/running이면 3초마다 `router.refresh()`. 워커 오프라인 안내는 렌더 중 + `worker_online=false`.
- 재시도 노출: job `failed(audio|render)` + 최신 run `failed` + 사유가 hook_too_long·text_too_long이 아닐 때. 두 사유는 "편집안으로 돌아가 고치기" 링크만(훅 필요 길이 수치는 API가 주지 않아 일반 안내).
- 범위 밖(ko만): 언어 탭·게시 문구·출처 목록. 사이드바에 내부 "제작"(/production) 항목 추가.
