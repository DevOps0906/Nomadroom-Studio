# task-019 YouTube 검색 후보 수집 (vidIQ 대체)

| 항목 | 내용 |
|---|---|
| 웨이브 | W3 |
| 선행 | task-006, task-008, task-013 |
| 위험도 | 높음 (→ 워커 model: opus) |
| 보안 영향 | 키·권한 · 노출 면 (YouTube API 키·할당량, 실행류 POST) |
| 담당 | builder + tester |
| 근거 | `docs/adr/0002-observation-quota.md`(2026-11-17 결정), `docs/01_PRD.md#7`(Q3)·`#9`, `docs/04_API.md#A-05`, `docs/02_ARCHITECTURE.md#3-1·#3-3`, `tasks/task-006.md#구현 결정`·`task-007.md#구현 결정` |
| 쓰기 허용 | `apps/api/app/youtube/**`, `apps/api/app/routes/collect_jobs.py`, `apps/api/app/collect/**`, `apps/api/tests/**`, `supabase/migrations/<새 번호>_*.sql`, `supabase/tests/**`, `apps/web/src/components/monitoring/**`, `docs/04_API.md`(팀장) |

## 할 것 (사용자 결정 2026-11-17: A안)
- 후보 발굴을 서버에서 YouTube `search.list`로 한다(워커 불필요). 프로필 조건 → 검색 파라미터(시장→regionCode·relevanceLanguage, 형식→videoDuration, 키워드→q, maxResults 50) → 결과 video_id로 `videos.list` 1차 관측 → 판정(prev 없음) → 후보·관측·판정 저장.
- 할당량: 검색 전용 일 상한 2,000 unit(상수) + 전체 방어선 8,000 unit(`reserve_quota`) 둘 다 원자적으로 예약. 초과 시 429 `QUOTA_EXCEEDED`.
- 수집 job 모델 재사용(kind=collect, `params.source = "youtube_search"`), 상태 전이는 `02#3-3`과 일치(서버가 동기 처리 후 done·failed). 멱등·60초·24시간 20건 상한 그대로.
- 화면: 검색 수집일 때 Chrome 준비 결과·워커 오프라인 안내는 숨기고 "vidIQ 수집: 준비 중" 안내만 표시.

## 하지 않을 것
- vidIQ 자동화(task-009, 준비 중), 예약 실행, 검색 결과의 vidIQ 수치 사용.

## 완료 조건 (실행 가능한 확인)
- [ ] `cd apps/api && pytest -q` 통과(YouTube 목): 검색 파라미터 매핑, 검색 일 상한·전체 방어선 429, 중복 후보 제외, 응답에서 빠진 영상 제외, 키 로그 0건
- [ ] `grep -rn "search.list\|/search" apps/api/app`는 `app/youtube/` 안 1곳만
- [ ] web `pnpm typecheck && pnpm lint && pnpm test` 통과, /monitor 캡처
- [ ] 단가·한도는 콘솔 재확인 필요(`미확인`) — 상수로 분리
