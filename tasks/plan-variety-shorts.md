# 팀장 브리프 — 예능형 쇼츠 제작 추가 (P0+P1)

> 기획 개정용 팀장 문서(목차·결정·미결). 본문은 각 docs 장에 쓴다. 근거: `docs/research/variety-shorts-zip-analysis.md`(CapCut 프로젝트·완성본 분석), ZIP `1-2. 예능형 실습 캡컷 프로젝트 파일 + 미디어 파일.zip`(저장소 밖). 카테고리형 브리프 `tasks/plan-category-shorts.md`의 결정(D-C2 로컬 워커·서명 URL, D-C3 Claude, D-C5 업로드 기본·URL 권리 확인)은 예능형에도 그대로 적용한다.

## 확정 결정 (사용자 2026-11-19)
| ID | 결정 |
|---|---|
| D-V1 | 순서: 공통 기반(task-020 스키마, 022 API)에 형식 칸(`format`)만 지금 넣는다. 예능형 전용 작업은 카테고리형 P0(W4) 다음 **새 웨이브 W6(예능형 P0)**, P1은 W7. 카테고리형 W5(P1)와 W6은 서로 독립(둘 다 선행 028) |
| D-V2 | 대사 자막: P0는 **운영자 수동 입력**. P1에서 **로컬 워커 받아쓰기**(faster-whisper, `secscan license` 통과 시)로 초안을 만들고 사람이 고친다. 음성 파일은 PC 밖으로 보내지 않는다 |
| D-V3 | 글꼴: 예제 글꼴(Cafe24 Ohsquare·여기어때 잘난체)의 상업 이용·워커 동봉 조건을 확인해 통과하면 쓴다. 안 되면 Pretendard Black(OFL)으로 대체한다 |
| D-V4 | 산출물: **MP4 + 리포트만**. CapCut 프로젝트는 읽지도 쓰지도 않는다(참고 자료) |
| D-C1 개정 | 카테고리형 기획의 "후속: 예능형 재배치"를 이 기획으로 옮긴다. 1080×1920은 예능형 프리셋으로만 도입하고, 카테고리형 1080×1920은 계속 후속 |

## 팀장 설계 결정
- **형식(format)**: `production_jobs.format` = `category`·`variety`, 기본 `category`. 작업 생성(A-09) 때 정하고 이후 바꿀 수 없다. `preset_version`은 형식별(예: `variety-1080-v1`). W4 동안 A-09는 `variety`를 400(`VALIDATION`, "준비 중")으로 막고, task-035에서 연다.
- **재사용**: prepare(구간 ≤180초·analysis·시트), 상태 전이(`02b#2`), 승인·리비전 고정, 렌더 큐(워크스페이스당 1건, 멱등 키), 서명 URL, 검수(A-17·A-18), 권리 확인은 형식과 무관하게 같다. 예능형에는 훅 음성이 없으므로 `hook_too_long`이 없고, A-10 훅 음성 업로드도 쓰지 않는다.
- **출력 프리셋**: 1080×1920, 30fps, H.264/AAC. 흰 캔버스, 영상 띠 y 560~1376(816px), 제목 영역은 띠 위쪽(약 328~496). 수치는 완성본 실측(분석 문서 #3)이고, 렌더러 상수 + `preset_version`으로 고정한다.
- **편집안 스키마 `spec`(format=`variety`)** — 시각 단위는 초
  - `header.lines`: 1~2줄. 줄바꿈과 빈 줄은 오류. 폭을 넘으면 자동 축소하고, 그래도 넘으면 `text_too_long`.
  - `cuts[]{src_start, src_end, scale, x, y}`: 배열 순서대로 출력. 출력 시각은 컷 길이의 누적이다. 원본 시각은 선택 구간 0초 기준이며 `0 ≤ src_start < src_end ≤ segment_len`. 원본 구간이 겹치거나 반복되어도 된다. 컷 길이는 0.2초 이상(미만이면 오류), 0.5초 미만이면 경고. 배율 1~3. x·y는 띠 중심 기준 px 이동. **띠가 빈 곳 없이 덮여야 한다**(위반이면 빈 화면 오류. 카테고리형 `Y+1080×배율` 규칙의 2축판). 컷은 1~60개. 출력 총길이는 180초 이하.
  - `subtitles[]{start, end, style, text}`: 출력 시각 기준. style은 `line`(검정 알약)·`punch`(빨강 알약). 자막끼리 겹치면 오류, 공백은 허용, 첫 자막이 0초가 아니어도 된다. 출력 총길이를 넘으면 오류. 문구는 공백만이면 오류. 1.4초 미만은 경고(카테고리형과 동일).
  - `reactions[]{start, end, text, x, y}`: 빨강+흰 테두리, 위치 자유(캔버스 안). 대사 자막과 겹쳐도 된다. 반응 자막끼리 시간이 겹치면 경고. 범위 초과는 오류.
  - 음성: 각 컷의 원본 소리를 그대로 쓰고 전체 음량을 정규화한다. 컷별 속도, J/L 컷, 색 효과, 별도 BGM은 지원하지 않는다(후속).
  - 경로 필드 금지 규칙은 카테고리형과 같다.
- **검증 코드**는 형식별 네임스페이스를 둔다(`cuts.empty_area`·`cuts.out_of_range`·`subtitles.overlap` 등). 서버 검증 모듈은 `format`으로 분기하고, 카테고리형 모듈(task-021)은 바꾸지 않는다.
- **렌더 어댑터**: 승인 리비전을 예능형 렌더 입력 JSON(`variety_project.json`, Nomadroom 자체 형식)으로 바꾼다. `format`은 W-05 `task.format`에 싣는다(R4).
- **리포트**: 해상도, 길이, 오디오 유무, 컷 수, 컷별 (출력 시작·원본 시작·길이), 사용 글꼴과 대체 여부.
- **받아쓰기(P1)**: 워커 작업 종류 `transcribe`(prepare 다음, 형식이 `variety`이고 요청이 있을 때). 산출 자산 kind는 `transcript`(JSON: 원본 시각 기준 segment 목록). 화면에서 "받아쓰기로 자막 채우기"를 누르면 선택한 컷에 맞춰 출력 시각으로 바꿔 subtitles 초안을 만든다. 실패하면 수동 입력으로 계속한다(가짜 자막 금지).
- **AI 초안(P1)**: A-14를 형식별로 확장한다. 예능형 입력은 transcript 텍스트와 0.5초 시트(저해상도), 후보 제목이다. 출력은 variety spec(컷 순서·자막·반응·제목)이다. 대사 텍스트가 Claude로 나가므로 `01#8`에 노출 면으로 기록한다. 원본 영상·음성 파일은 보내지 않는다. 호출 상한 Q7은 공용.
- **화면**
  - PROD-00 "새 작업"과 MON-01 "카테고리형 제작" 버튼을 **"내부 제작"** 하나로 합친다. PROD-01 맨 위에 형식 선택(카테고리형·예능형)을 두고, 준비를 시작한 뒤에는 잠근다.
  - PROD-02는 형식별 편집 패널로 나눈다. 예능형 패널은 컷 리스트(원본 in/out, 순서 위·아래 이동, 배율·x·y, 시트 썸네일), 출력 타임라인 바(컷 경계·자막 겹침 빨강), 대사 자막 행(style 선택), 반응 자막 행(x·y), 제목 1~2줄. 미리보기 영상은 P0에 두지 않고 시트 썸네일로 대신한다.
  - PROD-03은 그대로 쓴다(훅 안내 없음, 리포트에 컷 표).
- **인수 기준**: VAR-01~VAR-07(아래 작업 038·041). 기준 영상은 사용자 ZIP의 원본과 완성본이며, 저장소 밖에서 로컬로만 쓴다.

## 장별 담당 (planner 병렬)
| 장 | 담당 | 쓸 곳 |
|---|---|---|
| PRD | planner A | `docs/01_PRD.md` #2 스토리 S11(P0)·S12(P1), #3 범위 행 2개 + 카테고리형 행의 "예능형 재배치" 제거, #5 지표(형식별 제작 완료 수), #6 하지 않을 것(CapCut 내보내기·속도·J/L·색 효과), #7 Q9(글꼴)·Q10(faster-whisper 라이선스·모델 가중치), #8 위협 메모(대사 텍스트→Claude, 받아쓰기 모델 다운로드) |
| 화면 | planner B | `docs/03_SCREENS_UX.md` PROD-01·PROD-02 행 개정(형식 선택·예능형 패널), MON-01 버튼 문구, `design/spec.json`, 시안 `design/wireframes/PROD-02V.html` 신규 + index 링크 |
| 구조·API·데이터 | planner C | `docs/02b_PRODUCTION_FLOW.md`(형식 분기·transcribe 단계), `docs/04_API.md`(A-09 format, A-12 검증 분기, A-14 형식별, W-05 작업 종류 `transcribe`, W-06 payload format), `docs/05_DATA_MODEL.md`(format 칼럼, assets kind `transcript`, variety spec 필드 표), `docs/diagrams/variety-shorts-render-flow.mmd` |
| 작업 | 팀장 | task-020·022 개정, task-034~041 파일, `tasks/README.md` |

## 미결 질문 (문서 #7, 구현 전 확정)
- Q9 글꼴 2종의 라이선스(상업 이용·워커 동봉) — task-036 착수 전
- Q10 faster-whisper·Whisper 모델 가중치 라이선스와 모델 크기(제안: small, CPU) — task-039 착수 전
- 출력 총길이 상한(제안: 180초, 근거 없음 — 쇼츠 정책은 작업 시점에 확인)

## 팀장 결정 추가 (planner 보고 반영, 2026-11-19)
- 받아쓰기 모델의 배포처와 해시 고정은 task-039 착수 때 "구현 결정"으로 정한다(공식 배포처 + SHA-256 고정).
- 위협 메모에 넣은 "모델 파일은 pickle 등 자동 실행 형식 금지"를 유지한다.
- "AI 초안에 대사 텍스트가 전송됨" 고지 문구는 task-040에서 AI 초안 버튼 옆에 한 줄로 둔다.
- 출력 총길이 상한은 `01_PRD.md#7` Q11로 둔다(제안 180초).

## 리뷰 반영 결정 (reviewer doc, 2026-11-19)
- R1 받아쓰기 상태는 job 상태와 분리한다. `production_jobs.transcribe_state`(null·`queued`·`running`·`done`·`failed`)와 `transcribe_error`(null·코드)를 둔다. W-05 transcribe claim 조건은 format=`variety`·status=`review`·transcribe_state=`queued`이다. W-09 failed가 와도 job status는 바뀌지 않고 transcribe_state=`failed`만 기록한다. error_stage에는 넣지 않는다. 오프라인 지연(3분)도 같은 칸에 `worker_offline`으로 기록한다.
- R2 **A-19** `POST /production/jobs/{id}/transcribe`(P1): format=`variety`·status=`review`가 아니면 409이고, 이미 queued·running이어도 409이다. 성공은 202. 다시 요청하면 새 transcript 자산이 생긴다. PROD-02V api와 screen-data에 연결한다.
- R4 format은 W-05 `task.format`에 싣는다(W-06은 inputs만).
- R5 A-09 목록에 `format` 필터와 `items[].format`을 추가한다.
- R6 진입 버튼 용어는 "내부 제작"으로 통일한다(01 S7, 04 추적표, 02b).
- R7 좌표 기준: 원본을 캔버스 폭 1080에 맞춘 상태가 배율 1이다(원본 높이 = 1080×원본H/원본W×배율). x·y는 띠 중심(540, 968)에서 원본 중심까지의 px 이동이다. CapCut 정규화 x는 px = x×540으로 환산한다. 빈 화면 조건은 띠 사각형(0~1080 × 560~1376)이 이동·확대된 원본 사각형 안에 다 들어가는 것이다.
- R8 컷 수 1~60, 0.2초 오류, 0.5초 경고, 제목 1~2줄은 "가정"으로 표기하고 Q11에 묶는다.
- VAR-01 재현 규칙: 예제 컷 3(속도 0.95)은 속도 1.0으로 하고 원본 길이 = 출력 길이 1.37초로 입력한다. task-041의 회귀는 P1 변경 뒤 카테고리형을 다시 회귀하는 것이다(038의 VAR-05와 시점이 다르다).

## 작업 분해 (팀장 확정, W6=예능형 P0 · W7=예능형 P1)
| 번호 | 제목 | 웨이브 | 선행 | 위험도 | 담당 | 근거(장) |
|---|---|---|---|---|---|---|
| task-020(개정) | + `format` 칼럼·check, assets kind `transcript` 예약 | W4 | 002 | 높음 | builder + tester | 05 제작 테이블 |
| task-022(개정) | + A-09 `format` 저장(`variety`는 400 준비 중) | W4 | 020, 021 | 높음 | builder + tester | 04 A-09 |
| task-034 | 예능형 편집안 검증 모듈(cuts·subtitles·reactions·header) | W6 | 021, 028 | 보통 | builder + tester | 05 variety spec 표 |
| task-035 | 예능형 API 연결(A-09 허용·A-12 분기·렌더 어댑터·W-06 format) | W6 | 034 | 높음 | builder + tester | 04 A-09·A-12·W-06, 02b |
| task-036 | 예능형 렌더러(로컬 워커: 컷 재배치·흰 캔버스·띠·제목·자막 2종·반응·원본 음성·리포트·글꼴 라이선스) | W6 | 035 | 높음 | builder + tester | 분석 #2~#4, 05 variety spec, ADR 0003 |
| task-037 | PROD-01 형식 선택 + PROD-02 예능형 패널 + "내부 제작" 진입 통합 | W6 | 035 | 보통 | builder | spec PROD-01·PROD-02V·MON-01 |
| task-038 | 예능형 P0 인수 테스트 VAR-01~05 | W6 | 036, 037 | 보통 | tester | 01 S11 |
| task-039 | 로컬 받아쓰기 transcribe(faster-whisper, 새 의존성, transcript 자산, 자막 채우기) | W7 | 038 | 높음 | builder + tester | 01 Q10, 02b, 04 W-05 |
| task-040 | 예능형 AI 초안(A-14 형식 분기, transcript 입력) | W7 | 039, 029 | 높음 | builder + tester | 04 A-14, 01#8 |
| task-041 | 예능형 P1 인수 테스트 VAR-06·07 + 카테고리형 회귀 | W7 | 040 | 보통 | tester | 01 S12 |

### 인수 기준
- VAR-01: 실습 원본으로 예제 컷 14개를 입력하면 MP4가 1080×1920·30fps·H.264/AAC로 나온다. 길이는 컷 합계와 ±1프레임 안에서 맞고, 리포트의 컷 표는 편집안과 같다.
- VAR-02: 띠 밖(0~560, 1376~1920)에 원본 픽셀이 보이지 않는다. 띠 안에 빈 곳이 없다.
- VAR-03: 대사 자막(line·punch)과 반응 자막이 동시에 표시되고, 제목은 영상 내내 표시된다.
- VAR-04: 컷 범위 초과, 빈 화면, 자막 겹침, 0.2초 미만 컷은 승인이 막힌다. 0.5초 미만 컷과 1.4초 미만 자막은 경고만 낸다.
- VAR-05: 카테고리형 CAT-01~07 회귀가 통과한다.
- VAR-06(P1): 받아쓰기 초안으로 자막을 채운 뒤 수정해 렌더할 수 있다. 받아쓰기가 실패해도 수동 입력으로 끝까지 갈 수 있다.
- VAR-07(P1): AI 초안 출력이 variety spec 검증을 통과하거나, 오류가 필드 경로와 함께 표시된다.
