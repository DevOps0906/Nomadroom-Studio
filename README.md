# Nomadroom-Studio

## 대시보드 디자인 시안

**소재수집(정체)** 화면의 인터랙티브 시안입니다. 기존 Nomadroom의 왼쪽 메뉴와 상단 작업 탭을 기준으로 수집 조건과 후보 검증 결과를 배치했습니다.

[디자인 시안 HTML](./docs/design/Nomadroom_Dashboard_Design.html) · [HTML 내려받기](https://raw.githubusercontent.com/DevOps0906/Nomadroom-Studio/master/docs/design/Nomadroom_Dashboard_Design.html)

HTML을 내려받아 브라우저에서 열면 아래 항목을 예시 데이터로 확인할 수 있습니다.

- **프로필별 수집 조건**을 변경하고, Chrome 준비 완료와 창 확대 필요 상태의 표시 예시를 확인합니다.
- **제작 가능 · 근거 대기 · 조건 제외 · 사용한 소재**를 눌러 후보를 필터링합니다.
- **관측 근거**에서 조회수 비교 기간, 두 시점의 조회수, 증가율을 확인합니다.

Chrome·vidIQ 연결 상태는 화면 검토용 예시입니다.

## 진행 현황 (2026-11-16 기준)

기획(02)·UX(03)·기술 설계(05) 문서를 마쳤고, 구현은 아직 시작하지 않았습니다. MVP는 로그인 · 대시보드 · 소재수집(정체) 세 화면이며, 나머지 메뉴는 기존 운영 사이트 링크로 둡니다.

| 영역 | 현재 상태 |
|---|---|
| 기획 | PRD·린 검증·판정 규칙(`docs/01_PRD.md#9`) 작성, 문서 리뷰 반영 |
| UX·화면 | 화면 5개 표·와이어프레임(`design/wireframes/index.html`) |
| 기술 설계 | 아키텍처·ADR 2건·API 17개·테이블 11개 |
| 구현 | 미착수 (작업 17개 대기) |

제한: 벤치마킹은 실제 화면 확인 전(미확인), vidIQ 자동화 약관 미확인, YouTube API 할당량은 콘솔 재확인 필요.

### 작업 진행률
근거: `tasks/README.md` 작업 개수 기준.

| 웨이브 | 영역 | 완료 / 전체 |
|---|---|---|
| W1 | 프로젝트·DB·API 뼈대·보안 | 0 / 4 |
| W2 | 판정·관측·워커·API | 0 / 7 |
| W3 | 화면 | 0 / 6 |

### 구현된 주요 항목
- [x] 대시보드 디자인 시안(HTML)
- [x] 기획 문서 세트(00~05, ADR)

### 다음 개발 단계
- [ ] task-001 프로젝트 생성 · 토큰
- [ ] task-002 Supabase 스키마 · RLS · 시드 · ERD
- [ ] task-003 FastAPI 뼈대 · 인증

## 콘텐츠 바로가기

| 콘텐츠 | 화면 경로 | 기획·명세 문서 | 구현 코드 |
|---|---|---|---|
| 로그인 | `/login` | [03_SCREENS_UX](./docs/03_SCREENS_UX.md) · [와이어](./design/wireframes/AUTH-01.html) | 미구현 |
| 대시보드 | `/dashboard` | [03_SCREENS_UX](./docs/03_SCREENS_UX.md) · [와이어](./design/wireframes/DASH-01.html) | 미구현 |
| 소재수집(정체) | `/monitor` | [01_PRD#9 판정 규칙](./docs/01_PRD.md) · [와이어](./design/wireframes/MON-01.html) · [시안](./docs/design/Nomadroom_Dashboard_Design.html) | 미구현 |
| 기획 전체 | — | [PRD](./docs/01_PRD.md) · [아키텍처](./docs/02_ARCHITECTURE.md) · [API](./docs/04_API.md) · [데이터](./docs/05_DATA_MODEL.md) | — |
