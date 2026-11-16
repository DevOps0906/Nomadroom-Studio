# task-013 MON-01 소재수집 후보 목록

| 항목 | 내용 |
|---|---|
| 웨이브 | W3 |
| 선행 | task-006, task-008, task-010, task-011, task-012, task-018 |
| 위험도 | 높음 |
| 보안 영향 | 노출 면 (vidIQ 유래 비신뢰 값 렌더링, 실행류 호출 중계) |
| 담당 | builder (+ codex-reviewer design) |
| 근거 | `spec MON-01`, `docs/04_API.md#03 추적`, `docs/01_PRD.md#8` 웹 열, `design/wireframes/MON-01.html`, `docs/design/Nomadroom_Dashboard_Design.html`(소재수집 섹션) |
| 쓰기 허용 | `apps/web/src/app/(dashboard)/monitoring/page.tsx`, `apps/web/src/app/api/**`(중계 Route Handler), `apps/web/src/components/monitoring/**` |

## 할 것
- `spec MON-01` 구성 블록·상태·다음 화면대로 구현: 프로필 선택(최대 3)·후보 목록·상태 필터·Chrome 준비 상태·후보 가져오기(진행 폴링 3초 가정, 재시도·중지)·기록 검증 실행.
- Route Handler는 서버에서 FastAPI로 JWT 중계(브라우저→API 직접 호출 없음), 실행류에 `Idempotency-Key` 생성.
- 제목·채널명 텍스트 이스케이프, 썸네일 `i.ytimg.com` 허용 목록. 오류 상태: 할당량 방어선·워커 오프라인 문구는 spec 문구 그대로.

## 하지 않을 것
- 저장된 보기, 예약 실행, "사용한 소재" 토글(task-017), 조건 편집 화면(task-014).
- 셸 재구현 금지(task-018 사용).

## 완료 조건 (실행 가능한 확인)
- [x] `pnpm typecheck && pnpm lint && pnpm test` 통과(상태별 컴포넌트 테스트: 빈·로딩·진행·오류·Chrome 실패)
- [x] `<script>`가 든 제목이 텍스트로 렌더링되는 테스트 통과, 허용 외 썸네일 호스트 차단 테스트 통과
- [x] `shot`으로 3구간 캡처 확인

## 앞 작업에서 넘어온 것 (팀장, 2026-11-17)
- MON-D1 조건 설정은 spec상 /monitor 안 다이얼로그다. task-014는 `components/profiles/conditions-dialog.tsx`·`profile-list.tsx`와 독립 페이지 `/monitoring/profiles`로 만들었다 → 013에서 MON-01 프로필 영역에 이 다이얼로그를 연결하고, 독립 페이지는 유지하거나 MON-01로 redirect한다.
- 401은 `SESSION_EXPIRED_PATH`(server/api/client.ts)로 보낸다(루프 방지).

## 구현 계획 초안 (팀장, 2026-11-17 — challenger 검토 대상)
- 경로는 셸 내비와 spec이 쓰는 `/monitor`(기존 `(dashboard)/monitor/`를 채움). `/monitoring/profiles`는 `/monitor`로 redirect하고, MON-D1 다이얼로그는 /monitor 프로필 카드에서 연다.
- 읽기(A-03 목록·A-04 후보)는 Server Component에서 공용 클라이언트로 호출한다. 필터·정렬·검색·페이지는 URL searchParams로 둔다.
- 실행류(후보 가져오기 A-05 POST, 재시도, 중지, 기록 검증 A-07)는 Server Action으로 한다(Next Origin 검사). Idempotency-Key는 클릭마다 클라이언트에서 crypto.randomUUID로 만들어 hidden으로 보낸다(같은 제출을 다시 보내면 같은 키).
- 진행 폴링: 클라이언트가 3초마다 GET `/api/collect-jobs/[id]`(Route Handler, 서버에서 JWT 중계, 응답은 화면에 필요한 필드만)를 부른다. 종료 상태가 되면 멈추고 router.refresh 한다.
- 오류 문구: 429 QUOTA_EXCEEDED·RATE_LIMITED, 409, 워커 오프라인(worker_online=false), Chrome 상태 코드(detail enum)를 한국어로 바꾼다. 문구는 spec 그대로 쓴다.
- 비신뢰 값: 제목·채널·장르는 JSX 텍스트로만 넣는다(dangerouslySetInnerHTML 금지). 썸네일은 API가 null로 거른 값을 쓰되, 웹에서도 `https://i.ytimg.com/` host를 정확히 비교한다. next/image remotePatterns도 같은 host로 둔다.

## 구현 결정 (팀장, 2026-11-17 · challenger 검토 반영)
- 쓰기 허용(교체): `apps/web/src/app/(dashboard)/monitor/**`, `apps/web/src/app/(dashboard)/monitoring/profiles/**`(→ /monitor redirect·테스트 수정), `apps/web/src/app/api/collect-jobs/**`, `apps/web/src/components/monitoring/**`, `apps/web/src/server/api/**`(신규 파일 + client.ts에 선택 인자 `timeoutMs` 추가만), `apps/web/src/proxy.ts`(/api/* 미인증은 JSON 401), `apps/api/app/routes/collect_jobs.py`·`apps/api/tests/collect_jobs/**`(아래 active 경로만), `docs/04_API.md`(팀장).
- 🔴 진행 중 job 복구: API에 `GET /v1/collect-jobs/active` 추가 — 이 워크스페이스의 활성 collect job(queued·running·retrying) 1건을 GET /{id}와 같은 형식으로 200, 없으면 204(앞에 오프라인 평가). /monitor 서버 렌더에서 호출해 job id를 얻는다(URL·쿠키 보존 불필요). 워커 없이 queued로 남은 job도 화면에서 "워커 오프라인 — 수집 중지"로 멈출 수 있다.
- Idempotency-Key: 클라이언트가 "실행 의도" 단위로 UUID를 만든다. 요청 중이거나 타임아웃 뒤 다시 시도할 때는 같은 키를 쓰고, 성공하거나 확정 오류(4xx)를 받은 뒤 새 키로 바꾼다. 요청 중에는 버튼을 비활성화한다. Server Action은 UUID 형식을 다시 검증한다.
- 기록 검증(A-07): `apiFetch(..., { timeoutMs: 60_000 })`. TIMEOUT이면 "검증이 계속 진행 중일 수 있습니다. 잠시 뒤 새로고침하세요"를 보여 주고 키는 유지한다(같은 키 재요청은 기존 job 반환).
- 폴링 Route Handler `GET /api/collect-jobs/[id]`: id는 UUID만(아니면 400), 미인증·API 401은 JSON 401(클라이언트가 SESSION_EXPIRED_PATH로 이동), `Cache-Control: no-store`, 화면에 필요한 필드만 반환. proxy는 `/api/*` 미인증에 리다이렉트 대신 JSON 401을 준다.
- 폴링 클라이언트: 3초 간격. 탭이 숨겨지면 멈추고, 이전 요청이 끝나기 전에는 새로 보내지 않는다. 오류가 나면 간격을 2배로(최대 30초) 늘리고, 언마운트 시 정리한다. 종료 상태(done·failed·stopped)면 멈추고 router.refresh. queued이면서 worker_online=false면 10초 간격과 오프라인 안내. retry 성공 시 폴링을 다시 시작한다.
- searchParams: 잘못된 값은 기본값으로, 배열은 첫 값으로 정규화한다(400이 나지 않게). q는 100자에서 자르고 제어 문자는 제거한다.
- 오류 문구: 429는 code별(QUOTA_EXCEEDED "오늘 YouTube 조회 한도에 도달했습니다. 내일 다시 시도하세요" / RATE_LIMITED "잠시 후 다시 시도하세요"), 400·409는 API의 고정 한국어 message를 그대로 쓴다(서버 고정 문구라 안전). Chrome detail enum은 한국어로 매핑하고, 모르는 값은 "알 수 없는 원인".
- 후보 가져오기는 화면에 보이는 저장된 선택을 profile_ids로 명시해 보낸다. 선택을 저장하는 중에는 버튼을 막는다.
- 썸네일: next/image를 쓰지 않는다. `<img loading="lazy" referrerPolicy="no-referrer">`로 두고, URL을 파싱해 https·host `i.ytimg.com`·포트와 userinfo 없음을 확인한다(아니면 회색 자리 표시).
- 링크: "관측 근거"는 task-015에서 연결하므로 지금은 비활성 버튼으로 둔다. "영상 만들기"는 `NEXT_PUBLIC_OPS_SITE_URL` 고정 주소(후보 값을 href에 넣지 않음, 새 탭·noopener).
- 완료 조건 추가 테스트: 폴링 종료·숨김 일시정지·백오프, 401 JSON, UUID 거부, 키 재사용·중복 클릭, searchParams 정규화, active 204/200.
