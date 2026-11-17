# 02 아키텍처 — Nomadroom Studio

> 그림: [`diagrams/architecture.mmd`](diagrams/architecture.mmd) — 코드가 생기면 `deps2mmd`로 다시 생성
> 범위: MVP(로그인 · 대시보드 · 소재수집(정체)) + 카테고리형 제작(PROD, `02b_PRODUCTION_FLOW.md`). 나머지 메뉴는 운영 사이트 외부 링크(`01_PRD.md`). 스택 정본: `AGENTS.md#2`.

## 1. 구성 요소
| 요소 | 책임 | 기술 | 소유 경로 | 비밀 보유 |
|---|---|---|---|---|
| 웹 | 로그인·대시보드·소재수집(정체) 화면, 서버 측에서 API 중계 | Next.js 16 · React 19 · Tailwind v4 | `apps/web` | 없음 (Supabase anon 키·URL만, 공개 가능) |
| DB·인증 | 사용자·워크스페이스·프로필 조건·후보·관측값·판정·작업(job) 저장, RLS | Supabase Postgres · Auth | `supabase/` | service_role은 Supabase 안·API에만 |
| API | 판정·조건 검증, YouTube Data API v3 관측, 작업 등록, 워커 결과 수신 | FastAPI · Pydantic v2 | `apps/api` | YouTube 키 · service_role (클라우드 호스트 환경변수) |
| 수집 워커 | 운영자 PC에서 Chrome(Playwright)·vidIQ로 후보 수집, Chrome 준비 상태 보고 | Python · Playwright (`apps/api` 내 worker 모듈) | `apps/api/worker` | 워커 토큰만 (YouTube 키·service_role 없음). Chrome·vidIQ 로그인 프로필은 PC 로컬에만 |
| 제작 워커 | 운영자 PC에서 원본 준비(`prepare`: 구간 추출·analysis·시트)와 렌더(`render`: 훅 음성·합성·FFmpeg·리포트). 같은 워커 토큰·폴링 모델 | Python · FFmpeg · Pillow (`apps/api/worker`) | `apps/api/worker` | 워커 토큰만. 파일은 API가 준 서명 URL로만 송수신. DB·Supabase 키·LLM 키 없음 (`adr/0003-production-render-worker.md`) |
| 파일 저장소 | 제작 원본·분석·시트·음성·MP4·리포트 보관(작업별). 경로 규칙 `05_DATA_MODEL.md#storage` | Supabase Storage 비공개 버킷 `production` | `supabase/` | 서명 URL 발급은 API(service_role)만 |
| Claude API (AI 초안) | 승인된 구간 analysis·시트 → 편집안 초안(구조화 JSON) | Anthropic API (최신 모델은 구현 시 확인) | — | Anthropic 키는 API 요소만 |
| YouTube Data API v3 | 조회수·라이선스(C.C)·채널 정보 | 외부 | — | API 키는 API 요소만 |
| 운영 사이트 | 그 외 메뉴·"새 영상 만들기" | 외부(기존) | — | 해당 없음 (링크 이동만) |

결정(2026-11-16): API는 클라우드에 둔다(ADR-0001). 구체 호스팅처는 08 배포 단계에서 고른다.

## 2. 경계 규칙 (누가 누구를 부르나)
| 호출자 | 대상 | 방법 | 금지 |
|---|---|---|---|
| 브라우저 | Supabase | 직접 호출 안 함. 로그인·읽기는 웹 서버(Server Action·Server Component)가 anon 키 + 사용자 세션(httpOnly 쿠키)으로 대신, 전 테이블 RLS (사용자 결정 2026-11-16) | 브라우저 Supabase 클라이언트·Realtime, 쓰기 |
| 브라우저 | API | 직접 호출 안 함. 웹 서버(Route Handler)가 중계 | 브라우저에서 API 주소·키 노출 |
| 웹 서버 | API | HTTPS, `Authorization: Bearer <Supabase 사용자 JWT>` 전달. API가 JWT 서명·만료·워크스페이스 소속 검증 | JWT 없는 호출, 웹이 API 대신 YouTube·service_role 사용 |
| API | Supabase | service_role로 읽기·쓰기 (서버 환경변수) | 사용자 JWT 검증 없이 사용자 데이터 처리 |
| API | YouTube Data API | 서버에서 키로 호출, 일일 할당량 예산 준수 (`adr/0002-*.md`) | 후보 발굴 외 용도의 `search.list` 사용(발굴은 일 2,000 unit 상한 안에서만 — 2026-11-17 사용자 결정, `adr/0002`), 키를 응답·로그에 포함 |
| 워커 | API | 아웃바운드 HTTPS만, 워커 토큰으로 작업 요청 폴링·결과 전송. 로컬 포트 개방 없음 | 워커가 DB 직접 접속, 외부에서 워커 호출 |
| 워커 | Chrome·vidIQ | 로컬 Playwright, 운영자 로그인 프로필 | vidIQ 계정 정보를 API·DB로 전송 |
| 웹 | 운영 사이트 | 외부 링크(새 탭) | 토큰·세션을 링크에 실어 보내기 |
| 브라우저 | Storage | **업로드 한 가지만** 예외(대용량이라 직접 PUT, 팀장 결정 2026-11-18): API가 발급한 서명 업로드 URL(만료 `04_API.md#제작-api`)로 원본·훅 음성 PUT. 다운로드는 웹이 API에서 받은 서명 URL로 이동·재생. CSP connect-src에 Storage 출처 추가는 배포 체크리스트 | 서명 URL로 목록·다른 파일 접근, 버킷 공개 설정, 사용자 JWT로 Storage 직접 접근 |
| API | Storage | service_role로 서명 URL 발급·존재 확인(ffprobe 결과는 워커 보고로 검증). 경로는 서버가 생성 | 클라이언트·워커가 준 파일명·경로 사용 |
| API | Claude API | 서버에서 Anthropic 키로 호출(A-14만). 입력 범위는 `04_API.md` A-14, 출력은 편집안 스키마로 재검증 | 키를 응답·로그에 포함, 비신뢰 텍스트(제목·자막)를 지시문으로 취급, 작업당 횟수 상한 초과 호출 |
| 제작 워커 | API · Storage | 아웃바운드 HTTPS만. `/worker/v1/production/*`로 작업 수령·진행·완료 보고, 파일은 서명 URL로만. 워커는 작업 폴더 안에서만 파일명 결정 | JSON의 절대 경로·`..` 수용, Supabase 직접 접속, 로컬 포트 개방 |
| 제작 워커 | 원본 URL | `rights_confirmed`=true인 작업만 yt-dlp. 로그인·쿠키·접근 제한 우회 없음. 실패 시 업로드로 이관(`url_unavailable`) | 권한 확인 없는 다운로드, SSRF 규칙 위반 주소(`01_PRD.md#8`) |

공통: 금액 없음(결제 제외, D3). LLM 호출은 제작 AI 초안(A-14)만, 그 외 없음(D4, `01_PRD.md#6` 개정). 시간은 UTC 저장, 한국 시간 표시. 보안 레벨 정본은 `01_PRD.md#8`.

## 3. 주요 흐름
### 3-1. 후보 가져오기
| 단계 | 주체 | 동작 |
|---|---|---|
| 1 | 웹 | "후보 가져오기" 클릭 → 선택된 프로필(최대 3) 조건과 함께 API 호출 |
| 2 | API | 입력 검증 후 `collect` 작업(job)을 DB에 `대기`로 등록, job id 반환 |
| 3 | 워커 | 폴링으로 작업 수령 → Chrome 준비 확인(3-3) |
| 4 | 워커 | vidIQ로 프로필 조건별 후보(영상 id·제목·썸네일 등) 수집 |
| 5 | 워커 | 후보 묶음(실행당 ≤200, `01_PRD.md#7` Q3)을 API에 전송 → API가 중복 제거 후 저장 |
| 6 | API | 신규 후보를 YouTube API로 1차 관측(조회수·라이선스·채널) 저장 → 판정은 근거 대기 |
| 7 | 웹 | job 상태를 읽어 진행·완료 표시, 후보 목록 갱신 |

> 그림: [`diagrams/flow-1.mmd`](diagrams/flow-1.mmd)

### 3-2. 기록 검증 실행
| 단계 | 주체 | 동작 |
|---|---|---|
| 1 | 웹 | "기록 검증 실행" 클릭 → API 호출 (워커 불필요) |
| 2 | API | 마지막 관측 후 24시간 미만인 후보는 건너뜀(간격 24시간~7일) |
| 3 | API | 대상 후보를 50개 단위로 YouTube API 조회, 두 시점 관측값 저장 (할당량 예산 `adr/0002-*.md`) |
| 4 | API | 판정 규칙(`01_PRD.md#9`)으로 프로필별 판정 후 대표 판정 계산 |
| 5 | API | 할당량 소진·API 오류 시 남은 후보는 이전 판정 유지, 실패 사유 기록 |
| 6 | 웹 | 상태 지표 5개·후보 카드 갱신 |

> 그림: [`diagrams/flow-2.mmd`](diagrams/flow-2.mmd)

### 3-3. Chrome 준비 실패 → 재시도 / 중지
| 단계 | 주체 | 동작 |
|---|---|---|
| 1 | 워커 | 프로필별 Chrome 준비 점검(준비 완료 / 창 확대 필요 / 로그인 필요 등), 결과를 API로 전송 |
| 2 | 웹 | 프로필별 상태 표시. 실패 항목은 "해당 후보부터 재시도"·"수집 중지" 노출 |
| 3a | 웹→API→워커 | 재시도 선택: 실패한 프로필 지점부터 이어서 수집(이미 수집한 후보 유지) |
| 3b | 웹→API→워커 | 중지 선택: job을 `중지`로 변경, 워커는 현재 단계 정리 후 종료. 수집된 후보는 보존 |
| 4 | 워커 | 하트비트 3분 미수신 = 오프라인(가정) → API가 job을 `실패`로 표시 |

수치 정본(가정): 재시도 상한 3회(초과 시 재시도 불가) · 하트비트 3분 미수신 = 워커 오프라인. 04·05는 이 절을 링크한다.

수집 job 상태 전이 (collect, 정본 — 팀장 결정 2026-11-17):
| 현재 | 다음 | 주체 | 조건 |
|---|---|---|---|
| (없음) | queued | A-05 POST | 워크스페이스·kind당 활성 1건 |
| queued·retrying | running | W-01 claim | 조건부 갱신 1회(원자적). 같은 워커가 이미 running인 job이 있으면 그 job을 다시 돌려줌(재시작 복구) |
| queued·retrying | stopped | A-05 stop | 워커가 없으므로 즉시 |
| running | stopped | W-04(status=stopped) | `stop_requested`=true일 때만. A-05 stop은 `stop_requested`만 켬(W-02 응답으로 전달) |
| running | done·failed | W-04 | claim한 워커만 |
| running | failed | 오프라인 지연 평가 | claim한 워커 `last_seen_at` 3분 초과. W-01·W-02·A-05 GET/POST 때 평가(error=`worker_offline`) |
| failed | retrying | A-05 retry | `retry_count` < 3, +1, `resume_from_profile_id` = 첫 failed 프로필 |
| done·stopped | — | — | 종료(그 뒤 W-02~04는 409) |
- job_profile_runs: 다음 프로필의 후보가 들어오면 앞 프로필의 running 행은 done. job이 done이면 남은 running 행도 done, failed·stopped면 running 행만 failed. 재시도는 position 순으로 처음 done이 아닌 프로필부터. 워커 없이 queued로 남은 job은 자동 실패하지 않고 화면이 "워커 오프라인"을 보여 준다(사용자가 중지).

> 그림: [`diagrams/flow-3.mmd`](diagrams/flow-3.mmd)

### 3-4. 카테고리형 제작
분리: [`02b_PRODUCTION_FLOW.md`](02b_PRODUCTION_FLOW.md) (흐름·제작 job 상태 전이·실패 분기).

## 다이어그램 요청 (diagrammer)
- `diagrams/architecture.mmd` 갱신: 구성도(웹 · Supabase · API · 수집 워커(운영자 PC) · YouTube API · vidIQ/Chrome · 운영 사이트), 비밀 보유 요소 표시, 신뢰 경계(클라우드/운영자 PC) 구분.
- `diagrams/flow-1.mmd`: 시퀀스 — 후보 가져오기(3-1).
- `diagrams/flow-2.mmd`: 시퀀스 — 기록 검증 실행(3-2).
- `diagrams/flow-3.mmd`: 상태도 — job(대기·진행·재시도·중지·실패·완료)과 Chrome 준비 실패 분기(3-3).
- `architecture.mmd`에 제작 워커·Storage·Claude 추가. 제작 시퀀스 `flow-4.mmd`는 `02b_PRODUCTION_FLOW.md`.
- 제작 다이어그램(신규, 기존 파일 덮어쓰기 없음): `diagrams/flow-4.mmd`(제작 시퀀스) · `diagrams/flow-F-04.mmd`(화면 흐름 F-04) · `diagrams/category-shorts-render-flow.mmd`(렌더 흐름).
