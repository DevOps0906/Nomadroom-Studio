# 02b 제작 흐름 — 카테고리형·예능형 쇼츠 (PROD)

> 02 아키텍처에서 분리한 장. 구성 요소·경계 규칙은 `02_ARCHITECTURE.md#1·#2`, 결정 근거 `adr/0003-production-render-worker.md`, 컬럼 `05_DATA_MODEL.md#제작-테이블`, API `04_API.md`(A-09~A-19 · W-05~W-09).
> 그림: [`diagrams/flow-4.mmd`](diagrams/flow-4.mmd) (diagrammer 요청: 시퀀스 — 웹·API·Storage·제작 워커·Claude, 서명 URL 송수신, 실패·재시도 분기)

## 1. 흐름 (prepare → 편집안 → 승인 → render → 검수)
| 단계 | 주체 | 동작 |
|---|---|---|
| 1 | 웹→API | 작업 생성(MON-01·PROD-00 "내부 제작" 진입, A-09: 후보·URL·권리 확인) → 파일 업로드면 서명 URL로 Storage에 직접 PUT(A-10) → 준비 시작(A-11) `draft→preparing` |
| 2 | 제작 워커 | W-05 claim(`prepare`) → W-06 입력 URL로 다운로드(URL 작업(P1)은 `rights_confirmed`일 때 yt-dlp) → 구간 추출·analysis·시트 → W-07 업로드 URL로 올림 → W-09 완료. `preparing→review` |
| 3 | 웹→API | 편집안 저장(A-12, 서버 검증 정본)·선택적 AI 초안(P1, A-14) → 오류 0이면 승인(A-13, 리비전 고정) |
| 4 | 웹→API | 렌더 요청(A-15, `Idempotency-Key`) → `render_runs` queued, `review→rendering` |
| 5 | 제작 워커 | W-05 claim(`render`) → 훅 음성 실측(첨부 파일, 로컬 TTS는 (P1))·합성·FFmpeg·리포트 → W-07·W-09. `rendering→inspect` |
| 6 | 웹→API | 재생·리포트 확인(A-18) → 검수 승인(A-17) `inspect→done`, 또는 편집 수정(A-12) `inspect→review`(새 리비전) |
| 7 | 실패 | 워커가 단계·사유 코드와 함께 W-09 failed → `failed`. 원본 단계 재시도(A-11)·편집 수정(A-12)·같은 승인본 렌더 재시도(A-16: 새 render_run, 완료 파일 덮어쓰기 없음). 예외: `hook_too_long`·`text_too_long`(렌더러 폭 초과)는 편집안 검토로 되돌림(아래 전이표) |

## 1-1. 형식 분기 — 예능형(`format`=`variety`) {#형식-분기}
위 1~7단계·상태 전이·승인·렌더 큐·서명 URL·검수는 형식과 무관하게 같다(A-09는 W4 동안 `variety` 거부, task-035에서 허용). 다른 점만 적는다. 필드·검증 코드는 `05_DATA_MODEL.md#예능형-spec-필드`, 그림 [`diagrams/variety-shorts-render-flow.mmd`](diagrams/variety-shorts-render-flow.mmd).
| 단계 | 카테고리형 | 예능형 |
|---|---|---|
| 2 prepare | 구간 추출·analysis·시트 | 같음 |
| 2-1 transcribe (P1) | 없음 | `review`에서 A-19 요청 → `production_jobs.transcribe_state`=`queued` → W-05 `transcribe`(claim 조건: format=`variety`·status=`review`·transcribe_state=`queued`) → 로컬 받아쓰기 → `transcript` 자산(원본 시각 기준). 음성 파일은 PC 밖으로 보내지 않음. 화면에서 "받아쓰기로 자막 채우기" 시 선택한 컷에 맞춰 출력 시각으로 바꿔 subtitles 초안. 상태는 job 상태와 분리: `transcribe_state`(null·`queued`·`running`·`done`·`failed`)·`transcribe_error`. W-09 failed·오프라인 지연(3분, `worker_offline`)도 이 칸에만 기록하고 job `status`·`error_stage`는 불변. 실패하면 수동 입력으로 계속(가짜 자막 없음). 다시 요청하면 새 transcript 자산 |
| 3 편집안 | A-12 category spec, A-14 시트 기반 | A-12 variety spec, A-14(P1)는 transcript+시트 기반 |
| 5 render | 훅 음성 실측·shots 합성 | 어댑터가 `variety_project.json` 생성 → 컷별 trim·띠 크롭·흰 캔버스·제목·자막 2종·반응·원본 음성(음량 정규화)·리포트. 훅 음성 없음 |
| 7 실패 | `hook_too_long`·`text_too_long` → review | **`hook_too_long` 없음**. `text_too_long`만 review로 복귀 |

## 1-2. 유형 분기 — 쇼핑(`kind`=`shopping`)·일본어판 {#유형-분기}
1~7단계·상태 전이·승인·렌더 큐·검수는 같다. 쇼핑 필드·검증 코드는 `05_DATA_MODEL.md#쇼핑-spec-필드`, 그림 [`diagrams/shopping-shorts-render-flow.mmd`](diagrams/shopping-shorts-render-flow.mmd). 원본은 운영자 업로드만(자동 수집·다운로드 없음). 새 수치는 모두 가정.
| 단계 | 일반(카테고리형·예능형) | 쇼핑(`format`=`shopping`) |
|---|---|---|
| 1 생성 | A-09 `kind`=`general`, 형식 선택 | `kind`=`shopping`·`vertical`(`product`·`travel`)·`brief`·`affiliates`. 금지 품목(의약품·건강기능식품)은 체크·키워드 검사로 400. 원본 업로드 다건(A-10)·원본마다 권리 입력. 원본 3개 미만이면 경고만 |
| 2 prepare | 원본 1개 | **원본별** 구간 추출·analysis·시트(원본 수만큼 `source`·`analysis`·`sheet`, 한 task에서 순차 처리) |
| 3 편집안 | 형식별 spec | shopping spec(대본 4문장·문장별 컷·마스크·음성). 승인은 오류 0 + 모든 원본·BGM 권리 basis 입력 + `has_person`이면 `portrait_consent` |
| 5 render | 형식별 | TTS 또는 첨부 녹음 → 컷 길이를 문장 길이에 맞춤 → 자막 자동 배치 → 마스크·CTA·표기. 산출물에 게시 문구(A-21) 추가. TTS 실패는 `tts_failed`로 review 복귀(무음·가짜 음성 금지) |

### 여행(`vertical`=`travel`) 흐름 {#여행-흐름}
같은 1~7단계 위에 사진 컷과 선택적 AI 생성을 더한다. 설렘 서사 대본은 `tasks/plan-shopping-japanese.md`(상품 vs 여행). 비용·키 규칙은 `01_PRD.md#7` Q16·`#8`. 수치는 가정.
| 단계 | 동작 |
|---|---|
| 사진 업로드 | PROD-01S에서 공식 사진을 `image` 자산으로 업로드(A-10, 권리 basis 필수). 영상 원본(`source_upload`)도 함께 쓸 수 있음 |
| 사진 컷 | PROD-02S에서 `image` 컷은 기본 확대·이동 모션(`motion` pan·zoom·none, 무료, 렌더러 적용) |
| (선택) AI 생성 | 컷별로 고른다. A-22 견적(예상 비용·예산 잔액 표시) → 운영자 확인 → FastAPI가 플랫폼 호출(P1). 예산·상한 초과는 409로 거부, 같은 멱등 키는 중복 과금 없음. 결과는 `source_upload`(basis `ai_generated`)로 저장되고 `generation_runs`에 기록. API 없는 플랫폼은 운영자가 만든 영상을 업로드 |
| 검수 | AI 생성 컷은 컷마다 "검수 완료"(`reviewed`) 체크 필요(환각 대비). 미검수면 승인 불가(`gen.unreviewed`) |
| 편집·승인·렌더 | 이후 A-12·A-13·A-15는 쇼핑과 같음. 생성 실패는 job 상태를 바꾸지 않고 컷을 사진 모션으로 두고 계속 진행 |

### 일본어판(모든 형식, `lang`=`ja`) {#일본어판}
| 단계 | 동작 |
|---|---|
| 파생 | 승인된 ko 리비전에서 `edit_revisions.lang`=`ja`·`derived_from`=ko 리비전 ID로 새 리비전 생성. 컷·구도·마스크는 고정 복사, 텍스트만 교체 |
| 번역 | A-20: Claude가 구어체 일본어 초안(입력은 ko 텍스트만), 운영자가 수정 |
| 승인·렌더 | ja 리비전 승인 후 A-15 `lang`=`ja`. 멱등·동시 렌더 규칙은 ko와 같고 리비전이 언어별로 따로 있음 |
| 음성 | 카테고리형: 훅 TTS를 일본어로. 쇼핑: 내레이션 전체 일본어 TTS + 자막 자동 배치. 예능형: 대사 자막마다 일본어 TTS, 원본 소리 duck(가정 15%) |
| 넘침 | 예능형 TTS가 자막 구간 초과 → rate 상향(상한 가정 +30%) → 그래도 초과면 `dub_overflow` 경고(렌더 안 막음, 검수에서 확인) |
| 변경 감지 | ko 리비전이 바뀌면 ja에 "원본 변경됨" 경고(`derived_from`이 현재 ko 승인본보다 오래됨), 재파생 권유 |
- TTS(edge-tts, `01_PRD.md#7` Q6)는 쇼핑·일본어판 필수 경로다. 불가하면 첨부 녹음, 대체 TTS는 Q14.
- 게시(업로드·DM·링크 발급)는 자동화하지 않는다. 게시 문구 복사와 권장 시각 표시까지.

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
- 언어별 상태: 위 상태표는 ko 기준이다. ko가 `inspect`·`done`이면 ja 파생(A-20)과 ja 렌더(A-15)를 허용하고, ja 진행·완료·실패는 job 상태를 바꾸지 않고 `render_runs(lang=ja)`로 보여 준다.
