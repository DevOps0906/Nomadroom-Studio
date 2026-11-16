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
- [ ] `pnpm typecheck && pnpm lint && pnpm test` 통과(상태별 컴포넌트 테스트: 빈·로딩·진행·오류·Chrome 실패)
- [ ] `<script>`가 든 제목이 텍스트로 렌더링되는 테스트 통과, 허용 외 썸네일 호스트 차단 테스트 통과
- [ ] `shot`으로 3구간 캡처 확인

## 앞 작업에서 넘어온 것 (팀장, 2026-11-17)
- MON-D1 조건 설정은 spec상 /monitor 안 다이얼로그다. task-014는 `components/profiles/conditions-dialog.tsx`·`profile-list.tsx`와 독립 페이지 `/monitoring/profiles`로 만들었다 → 013에서 MON-01 프로필 영역에 이 다이얼로그를 연결하고, 독립 페이지는 유지하거나 MON-01로 redirect한다.
- 401은 `SESSION_EXPIRED_PATH`(server/api/client.ts)로 보낸다(루프 방지).
