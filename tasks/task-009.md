# task-009 로컬 워커 (Playwright Chrome · vidIQ)

| 항목 | 내용 |
|---|---|
| 웨이브 | W2 |
| 선행 | task-007, **vidIQ 약관 확인(사용자가 확인 후 결정 — 그 전까지 보류)** |
| 위험도 | 높음 |
| 보안 영향 | 의존성 · 키·권한 (Playwright, vidIQ 로그인 프로필, 워커 토큰) |
| 담당 | builder |
| 근거 | `docs/adr/0001-worker-location.md`, `docs/04_API.md#워커 API`, `docs/02_ARCHITECTURE.md#3-1·#3-3`, `docs/01_PRD.md#8` 워커 열 |
| 쓰기 허용 | `apps/worker/**`, `.env.example` |

## 할 것
- 운영자 PC 워커: W-01 폴링(5~10초 가정) → Playwright Chrome으로 vidIQ 조건 수집 → W-03 전송 → W-04 종료, W-02로 Chrome 상태(`ready`·`resize_needed`·`login_needed`·`error`) 보고, `stop_requested` 존중.
- 실행 간격 제한·실행당 후보 200 상한. Chrome 프로필·토큰은 저장소 밖 경로(환경변수), 로그에 쿠키·경로 금지.
- 파싱 결과는 신뢰하지 않고 전송 전 형식 검증.

## 하지 않을 것
- DB 직접 접속, 로컬 포트 개방, 약관 확인 전 vidIQ 실접속 구현, 쿠키 저장·커밋.

## 완료 조건 (실행 가능한 확인)
- [ ] vidIQ 약관 확인 결과가 `docs/01_PRD.md#8`에 팀장 기록됨(없으면 착수 금지)
- [ ] `cd apps/worker && pytest -q`(vidIQ 페이지는 고정 HTML 픽스처, FastAPI는 목) 통과
- [ ] `~/.claude/nomad/bin/secscan license` GPL·AGPL 0건
- [ ] 로그 캡처에 쿠키·토큰·프로필 경로 0건
