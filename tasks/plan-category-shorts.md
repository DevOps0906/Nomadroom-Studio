# 팀장 브리프 — 카테고리형 쇼츠 제작 추가 (P0+P1)

> 기획 개정용 팀장 문서(목차·결정·미결). 본문은 각 docs 장에 쓴다. 근거: `Nomadroom_Category_Shorts_PRD.md`(기획서), `docs/research/category-shorts-zip-analysis.md`(배포본 분석), ZIP `카테고리형 영상제작_배포용 .zip`의 `category-shorts/SKILL.md`·`references/project-format.md`·`references/style.md`·`tests/check.py`.

## 확정 결정 (사용자 2026-11-18)
| ID | 결정 |
|---|---|
| D-C1 | 범위는 **P0+P1**. P2(일본어)·후속(1080×1920, 예능형 재배치, 롱투숏, 동시 렌더)은 하지 않을 것 |
| D-C2 | 렌더링(원본 준비·시트·음성·합성·인코딩)은 **로컬 PC 워커**(ADR 0001 방식). 워커는 FastAPI `/worker/v1/*`만 호출하고 DB·Supabase 키를 갖지 않는다. 파일은 API가 발급한 Supabase Storage **서명 URL**로만 주고받는다 |
| D-C3 | AI 초안 LLM은 **Claude**(Anthropic API, 최신 모델). 키는 FastAPI에만. 입력은 승인된 원본 구간의 analysis·시트, 출력은 편집안 스키마 그대로(구조화 JSON). 사용자가 고칠 수 있다. PRD#6 "MVP LLM 금지"를 이 기능 한정으로 개정 |
| D-C4 | 훅 음성: P0는 **첨부 음성 파일**만. P1 TTS는 edge-tts를 `secscan license`로 확인해 통과하면 **로컬 워커에서만** 쓴다. 실패·거부 시 첨부 음성 경로를 유지한다(무음·가짜 음성 대체 금지) |
| D-C5 | 원본: **파일 업로드가 기본**. URL은 운영자가 "사용 권한 확인"을 체크했을 때만 로컬 워커가 yt-dlp로 받는다. 로그인·쿠키·접근 제한 우회는 금지. 실패하면 업로드로 넘어간다 |
| D-C6 | 댓글 카드 레이어는 **제작 화면에서 직접 입력**(문구·표시 구간·위치). 운영 사이트 연동은 이후 |
| D-C7 | 진행 방식: task-019 구현과 병행. 카테고리형 구현 작업은 이 기획이 승인된 뒤 019 다음에 이어 붙인다 |

## 팀장 설계 결정 (분석 문서 반영)
- 출력 프리셋은 배포본 그대로 608×1080·30fps·H.264/AAC, 프리셋 버전을 기록한다. 폰트 3종(OFL)과 licenses 폴더를 보존한다.
- 타임라인: 원본 기준 시작 시각(`source_start_sec`)과 편집 0초 기준을 따로 저장한다(CAT-02).
- 편집안 검증은 서버(Pydantic)가 정본이다. 배포본 `validate()`와 같은 규칙에 1.4초 미만 경고를 더한다. 경고는 렌더를 막지 않는다. 오류는 막는다: 공백, 겹침, 범위 초과, 빈 화면 배율·Y, NaN, 제목 2줄 위반, 너무 긴 문구, 첫 자막 0초 아님, 훅+0.08초가 첫 자막보다 긴 경우.
- 경로 보안: 웹과 API는 작업 ID·자산 ID만 주고받는다. 워커는 작업 폴더 안에서만 파일명을 정한다. JSON의 절대 경로와 `..`는 거부한다.
- 상태: 초안 → 원본 준비 → 편집안 검토 → 렌더링 → 검수 대기 → 완료. 실패는 단계와 사유 코드를 함께 둔다. 기획서 #4 상태도를 따른다.
- 승인 고정: 승인 후 편집하면 새 리비전이 생긴다. 렌더는 (작업, 리비전, 언어=ko)마다 하나만 진행한다(멱등 키). 재시도는 완료 파일을 덮어쓰지 않는다.
- 진입: MON-01 "영상 만들기 →"(외부 운영 사이트)는 유지한다. 별도로 "카테고리형 제작" 버튼을 두어 내부 제작을 시작한다(CAT-01: 후보 ID·제목·원본 URL·라이선스를 넘김). 앱 셸 사이드바 "제작·업로드"는 외부 링크로 두고, 내부 화면은 `/production`이다.
- 화면 ID: PROD-00 제작 작업 목록, PROD-01 원본·구간·출처, PROD-02 편집안(분석 시트 패널 + 제목·훅·자막·구도 + 댓글·출처 탭 + AI 초안 버튼), PROD-03 작업·검수(진행·실패 사유·재시도·MP4 재생·리포트·다운로드).
- 데이터(초안, 이름은 planner가 05 규칙으로 확정)
  - `production_jobs`: 작업 메타, 상태, 후보 FK, 원본 URL, 권리 확인, 구간.
  - `production_assets`: 원본, source, 시트, 훅 음성, mp4, report. Storage 경로와 종류를 담는다.
  - `edit_revisions`: 편집안 jsonb, 리비전, 승인 시각, 검증 결과.
  - `render_runs`: 리비전, 언어, 멱등 키, 상태, 오류 단계, 결과 자산.
  - 모두 RLS를 건다. Storage 버킷은 비공개로 둔다.
- 워커 작업 종류: `prepare`(구간 추출·analysis·시트), `render`(음성·합성·리포트). 수집 워커와 같은 토큰·폴링 모델을 쓴다. 기존 W-01~W-04와 이름이 겹치지 않게 W-05부터 번호를 매긴다.

## 장별 담당 (planner 병렬)
| 장 | 담당 | 쓸 곳 |
|---|---|---|
| PRD 개정 | planner A | `docs/01_PRD.md` #2 스토리 S7~, #3 범위, #5 지표(제작 완료 수), #6 개정, #7 미결, #8 노출 면(업로드·서명 URL·LLM·URL 다운로드) + `docs/adr/0003-production-render-worker.md` |
| 화면 | planner B | `docs/03_SCREENS_UX.md` 화면·상태·흐름 표에 PROD-00~03 행 추가(형식 그대로) |
| 구조·API·데이터 | planner C | `docs/02_ARCHITECTURE.md` 구성 요소·흐름 3-4(제작), `docs/04_API.md` 사용자 A-09~·워커 W-05~, `docs/05_DATA_MODEL.md` 테이블 |

## 미결 질문 (문서 #7에 기록, 구현 전 확정)
- 작업 파일 보관 기간·용량(제안: 완료 후 30일, 원본은 렌더 완료 7일 후 삭제)
- edge-tts 라이선스·이용 조건 확인 결과(D-C4)
- Claude 호출 비용 상한(제안: 작업당 초안 3회)
- 업로드 원본 최대 크기(제안: 500MB, 180초 구간)

## 팀장 결정 추가 (planner 보고 반영)
- 서명 URL 만료: 업로드 15분, 다운로드 10분. 워커 입력·산출물 URL도 같다(워커는 만료 시 다시 발급받는다).
- AI 초안 입력: 0.5초 시트 이미지(저해상도 JPEG)와 analysis.json, 후보 제목만 보낸다. 원본 영상·음성 파일은 Claude로 보내지 않는다.
- URL 다운로드 보호: 사설망·루프백·file:·비 http(s) 거부(SSRF 방지)를 채택한다. 리다이렉트 후 주소도 다시 검사한다.
- ADR 0003 대안 기각 사유(클라우드 렌더: 비용·IP 차단)를 수용한다. reviewer 통과 후 "승인"으로 바꾼다.
- PROD-00의 "새 작업"(후보 없이 직접 시작)은 유지한다. TTS 실패 안내는 "(P1 TTS 사용 시)"로 표기한다.
- 브라우저 → Storage 서명 URL 직접 PUT 허용(02 경계 예외, 대용량 업로드). CSP connect-src에 Storage 출처 추가는 배포 체크리스트.
- 훅 음성 길이: 승인 때는 null 허용(브라우저 audio 메타데이터 길이는 참고로만 표시). 렌더 워커가 실측해 `hook_too_long`으로 실패시키고 편집안 검토로 되돌린다.
- 승인(A-13)과 렌더 요청(A-15) 분리 수용.
- 02가 상한을 넘으면 3-4 제작 흐름을 `docs/02_ARCHITECTURE.md`에서 `docs/02b_PRODUCTION_FLOW.md`로 분리하고 링크한다.
- 제작 워커는 수집 워커와 같은 토큰·같은 실행 파일. 작업 종류로 구분한다.
- 배포본 규격 사본: `docs/research/category-shorts-ref/`(project-format·style·SKILL·check.py). 자막 kind는 배포본 값 `white`·`paren`·`emph` 그대로. 제목 글자 수 상한 대신 렌더러 자동 축소 + 폭 초과 오류.

## 검토 반영 목록 (2026-11-18, reviewer doc + designer UX → planner 1회 반영)
문서(reviewer)
- R1 05 spec: items.y 310~1030, items 최소 1개, 자막 text 공백 불가, duration 0.1 이상·analysis 길이+0.05 이하·180 이하. hook.text 필수는 배포본보다 강화한 것(의도) — 표에 명시.
- R2 훅 길이는 서버 승인 검사에서 제외(05의 `hook.too_long` 삭제). 03은 "렌더 후 안내"로 옮기고, 브라우저 메타 길이가 있으면 PROD-02에 경고만 표시.
- R3 훅 공식 정본은 04 W-09: `hook+0.08 > min(duration, 첫 자막 종료) + 0.02`면 `hook_too_long`. 02b·03·01은 링크만.
- R4 A-09에 PATCH 추가(draft·failed(prepare)에서 구간·권리 확인·URL 수정). 매핑: PROD-02에 A-10(훅 음성 업로드), MON-01에 A-09.
- R5 P1 표기 통일: URL 원본(`source_kind=url`), 댓글·출처 overlays, AI 초안(A-14), TTS는 02b·03·04·05에 "(P1)" 표기. 01 #3 표와 일치시킨다.
- R6 렌더 동시 1건: render_runs의 queued·running 합산 부분 unique(workspace 기준)를 05에 명시, 04·02b와 일치.
- R7 04 공통: W-06 GET 10분, W-07 PUT 15분.
- R8 flow-4.mmd는 신규(기존 덮어쓰기 없음). 02의 다이어그램 목록에 flow-4(제작 시퀀스)·flow-F-04·category-shorts-render-flow를 등록.
- R9 근거 없는 수치(A-15 429 60초, A-09 ≤180 가정, A-16 3회)는 "가정" 표시 또는 Q로. `worker_offline`은 서버 생성 코드로 05·W-09에 명시. 너무 긴 문구는 렌더러 폭 초과 = `text_too_long`(렌더 실패 → review 복귀, hook_too_long과 같은 처리), 서버는 공백만 검사.
- R10 ADR 0003 상태를 "승인"으로.
화면(designer UX)
- U1 PROD-02 구성: 자막 행 리스트(＋행·삭제·구간·유형·문구)와 구도(컷) 행 리스트, 구간 타임라인 바(겹침·공백 빨강), 자막 행 1.4초 미만 노랑 배지, 훅 입력 아래 "훅 N초 / 첫 자막 M초" 카운터(메타 있을 때).
- U2 PROD-02 버튼: "저장"(오류 허용 초안 저장, 서버 검증 결과 표시)·"승인"(오류 0일 때). 승인 후 PROD-03으로 이동해 "렌더 요청" 버튼. 승인됨·렌더 미시작 상태 문구. "검증" 별도 버튼은 없앰(저장이 검증 포함).
- U3 PROD-02 ~767 탭 4개(시트·편집안·댓글·출처), 저장·승인 하단 고정, 승인 비활성 사유 링크. 취소 시 미저장 변경 확인.
- U4 PROD-03: 검수 대기에 "검수 승인 → 완료"(A-17) 버튼, 재시도는 실패 때만, hook_too_long·text_too_long은 "편집안으로 돌아가 고치기" 링크, 렌더 요청 중 버튼 비활성.
- U5 PROD-00 빈 상태 "소재수집 열기" 버튼(구성에 명시).
- U6 PROD-01: "사용 권한 확인" 체크를 URL 앞에, 원본 준비 완료 시 "편집안으로" 활성 버튼, 길이 힌트 "0 초과 180 이하".

## 작업 분해 (팀장 확정, 웨이브 W4=P0 · W5=P1)
| 번호 | 제목 | 웨이브 | 선행 | 위험도 | 담당 | 근거(장) |
|---|---|---|---|---|---|---|
| task-020 | 제작 스키마·RLS·Storage 버킷 | W4 | 002 | 높음 | builder + tester | 05 제작 테이블·Storage, 02b 상태 |
| task-021 | 편집안 검증 모듈(배포본 validate 동등 + 1.4초 경고) | W4 | 003 | 보통 | builder + tester | 05 spec 표, ref/render.py·check.py |
| task-022 | 제작 작업 API A-09~A-13·A-17·A-18(서명 URL) | W4 | 020, 021 | 높음 | builder + tester | 04 A-09~A-13·A-17·A-18, 01#8 |
| task-023 | 렌더 요청·재시도 A-15·A-16 + 워커 API W-05~W-09 | W4 | 022 | 높음 | builder + tester | 04 A-15·A-16·W-05~W-09, 02b |
| task-024 | 로컬 제작 워커 prepare·render(배포본 이식·어댑터·경로 보안·첨부 음성·폰트 라이선스) | W4 | 023 | 높음 | builder + tester | ADR 0003, 02b, ref/*, 05 spec 매핑 |
| task-025 | PROD-00·PROD-01 화면 + MON-01 카테고리형 제작 버튼 | W4 | 022 | 보통 | builder | spec PROD-00, spec PROD-01, spec MON-01 |
| task-026 | PROD-02 편집안 화면 | W4 | 022, 025 | 보통 | builder | spec PROD-02 |
| task-027 | PROD-03 작업·검수 화면 | W4 | 023, 025 | 보통 | builder | spec PROD-03 |
| task-028 | P0 인수 테스트 CAT-01~07(실영상 렌더·ffprobe) | W4 | 024, 026, 027 | 보통 | tester | 01 S7~S9, 기획서 #5 |
| task-029 | AI 초안 A-14(Claude, 키는 API에만, 새 의존성) | W5 | 028 | 높음 | builder + tester | 04 A-14, 01#8, Q7 |
| task-030 | TTS(edge-tts 라이선스 확인 → 워커 전용, 실패 시 첨부 음성) | W5 | 028 | 높음 | builder | 01 Q6, 02b |
| task-031 | URL 원본(권리 확인 체크·yt-dlp·SSRF 방지) | W5 | 028 | 높음 | builder + tester | 01#8 SSRF, 04 A-09 PATCH·W-06 |
| task-032 | 댓글·출처 오버레이 레이어(렌더러+PROD-02 탭) | W5 | 028 | 보통 | builder | 05 overlays, spec PROD-02 |
| task-033 | P1 인수 테스트 CAT-08 + 회귀 | W5 | 029, 030, 031, 032 | 보통 | tester | 01 S10 |

## 사용자 결정 (2026-11-19, W5~W9 연속 진행 지시와 함께)
- Q9~Q15는 문서 기본값으로 진행: Q9 라이선스 근거 없으면 Pretendard Black(OFL) 대체 · Q10 secscan 통과 시에만 faster-whisper small·CPU, 아니면 수동 입력만 · Q11 예능형 총길이 180초·컷 1~60 · Q12 영상 안 고정 문구(ko "제휴 링크 포함")+게시 문구 첫 줄 · Q13 제휴처 이미지 사용 안 함(rights basis 구분) · Q14 edge-tts 불가 시 해당 기능 보류 · Q15 미확인 이미지 없이 현재 근거로.
- Claude API(task-029·040·048): 목으로만 구현·테스트, 실제 호출은 사용자가 키를 넣은 뒤 직접 확인(비용 0).
- Q16(task-054): xAI 어댑터·비용 상한 장치만 만들고 기본 꺼짐(상한 0원). 키 발급·예산은 나중에 사용자 결정.
