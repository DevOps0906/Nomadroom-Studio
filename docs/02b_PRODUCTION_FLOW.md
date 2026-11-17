# 02b 제작 흐름 — 카테고리형 쇼츠 (PROD)

> 02 아키텍처에서 분리한 장. 구성 요소·경계 규칙은 `02_ARCHITECTURE.md#1·#2`, 결정 근거 `adr/0003-production-render-worker.md`, 컬럼 `05_DATA_MODEL.md#제작-테이블`, API `04_API.md`(A-09~A-18 · W-05~W-09).
> 그림: [`diagrams/flow-4.mmd`](diagrams/flow-4.mmd) (diagrammer 요청: 시퀀스 — 웹·API·Storage·제작 워커·Claude, 서명 URL 송수신, 실패·재시도 분기)

## 1. 흐름 (prepare → 편집안 → 승인 → render → 검수)
| 단계 | 주체 | 동작 |
|---|---|---|
| 1 | 웹→API | 작업 생성(A-09: 후보·URL·권리 확인) → 파일 업로드면 서명 URL로 Storage에 직접 PUT(A-10) → 준비 시작(A-11) `draft→preparing` |
| 2 | 제작 워커 | W-05 claim(`prepare`) → W-06 입력 URL로 다운로드(URL 작업(P1)은 `rights_confirmed`일 때 yt-dlp) → 구간 추출·analysis·시트 → W-07 업로드 URL로 올림 → W-09 완료. `preparing→review` |
| 3 | 웹→API | 편집안 저장(A-12, 서버 검증 정본)·선택적 AI 초안(P1, A-14) → 오류 0이면 승인(A-13, 리비전 고정) |
| 4 | 웹→API | 렌더 요청(A-15, `Idempotency-Key`) → `render_runs` queued, `review→rendering` |
| 5 | 제작 워커 | W-05 claim(`render`) → 훅 음성 실측(첨부 파일, 로컬 TTS는 (P1))·합성·FFmpeg·리포트 → W-07·W-09. `rendering→inspect` |
| 6 | 웹→API | 재생·리포트 확인(A-18) → 검수 승인(A-17) `inspect→done`, 또는 편집 수정(A-12) `inspect→review`(새 리비전) |
| 7 | 실패 | 워커가 단계·사유 코드와 함께 W-09 failed → `failed`. 원본 단계 재시도(A-11)·편집 수정(A-12)·같은 승인본 렌더 재시도(A-16: 새 render_run, 완료 파일 덮어쓰기 없음). 예외: `hook_too_long`·`text_too_long`(렌더러 폭 초과)는 편집안 검토로 되돌림(아래 전이표) |

## 2. 제작 job 상태 전이 (정본 — 기획서 #4 상태도, 값은 `05_DATA_MODEL.md#production_jobs`)
| 현재 | 다음 | 주체 | 조건 |
|---|---|---|---|
| (없음) | draft | A-09 | 후보 없이도 생성 가능("새 작업"). URL이면 `rights_confirmed` 필수 |
| draft·failed(prepare) | preparing | A-11 | 원본 확보(업로드 완료 또는 URL). 재시도 상한 3회(`02_ARCHITECTURE.md#3-3`과 동일, 가정) |
| preparing | review | W-09 done | analysis·시트·`source` 자산 확인 후. 첫 편집안 리비전 생성 |
| review | rendering | A-15 | 승인 리비전·오류 0·같은 (job, 리비전, 언어) 활성·완료 run 없음·워크스페이스 동시 렌더 1건 |
| rendering | inspect | W-09 done | MP4·리포트 자산 확인 후 |
| rendering | review | W-09 failed(`hook_too_long`·`text_too_long`) | 훅 길이 판정식은 `04_API.md` W-09(정본). 문구 폭 초과는 `text_too_long`. 편집안·훅 문구 보존, run은 failed, 사유(훅은 필요 길이)를 화면에 안내 |
| inspect | done · review | A-17 · A-12 | 검수 승인 · 편집 수정(새 리비전) |
| preparing·rendering | failed | W-09 failed · 오프라인 지연 평가 | 진행 보고(W-08) 3분 초과 = 서버 생성 코드 `worker_offline`(`05_DATA_MODEL.md` error_code, `02_ARCHITECTURE.md#3-3` 규칙 재사용) |
| failed | preparing · review · rendering | A-11 · A-12 · A-16 | 실패 단계가 prepare / 편집·음성 문제 / 렌더 일시 오류 |
- 렌더 중(`rendering`) 편집안 저장은 409. 완료된 run의 파일은 불변이고 재시도는 새 run·새 자산(`05_DATA_MODEL.md#storage`의 경로가 자산 ID를 포함).
- 훅 음성 길이는 승인 때 null 허용, **렌더 워커가 실측**(정본 `04_API.md` W-09).
