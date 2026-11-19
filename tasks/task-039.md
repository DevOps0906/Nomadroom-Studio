# task-039 로컬 받아쓰기 transcribe

| 항목 | 내용 |
|---|---|
| 웨이브 | W7 |
| 선행 | task-038 |
| 위험도 | 높음 |
| 보안 영향 | 새 의존성(faster-whisper·모델 가중치, Q10) · 워커 작업 종류 추가 |
| 담당 | builder + tester |
| 근거 | `docs/01_PRD.md#7` Q10, `docs/02b_PRODUCTION_FLOW.md`, `docs/04_API.md` A-19·W-05·W-09, `docs/05_DATA_MODEL.md`(transcript) |
| 쓰기 허용 | `apps/worker/production/transcribe/**`, `apps/api/app/routes/worker_production.py`, `apps/api/app/routes/production_jobs.py`(받아쓰기 요청), PROD-02 "받아쓰기로 자막 채우기", 해당 테스트 |

## 할 것
- 착수 전 `secscan license`로 faster-whisper·모델 가중치 확인(GPL·AGPL 거부).
- A-19 `POST /production/jobs/{id}/transcribe`(variety·review 아니면 409, queued·running 중 409, 성공 202, 재요청은 새 transcript 자산). `production_jobs.transcribe_state`(queued·running·done·failed)·`transcribe_error` 기록: W-05 claim 조건 format=variety·status=review·transcribe_state=queued, W-09 failed·오프라인 지연(`worker_offline`)은 transcribe_state=failed만 쓰고 job status·error_stage 불변.
- 작업 종류 `transcribe` → transcript 자산(원본 시각 segment). 화면에서 선택 컷 기준 출력 시각 자막 초안. 실패 시 수동 입력 유지.

## 하지 않을 것
- 음성을 PC 밖(외부 API)으로 전송, 실패 시 가짜 자막 생성.

## 완료 조건 (실행 가능한 확인)
- [ ] `pytest -q`(api·worker) 통과, 받아쓰기 실패 경로 테스트 포함
- [ ] `secscan license` 결과를 task 파일 "구현 결정"에 기록

## 착수 결정 (2026-11-20, challenger 검토 반영 · 팀장 결정)
- 순서: task-042 커밋 뒤 착수(같은 claim·finish 함수 교체). 마이그레이션은 042 다음 번호, 직전 최신 본문 위에 diff만.
- 0단계(착수 조건): faster-whisper·ctranslate2·onnxruntime·av의 Python 3.14 Windows wheel 존재와 라이선스(PyAV 동봉 FFmpeg configure 포함, Systran/faster-whisper-small 모델 카드·원본 Whisper)를 먼저 확인해 구현 결정에 기록. GPL·AGPL이 끼거나 wheel이 없으면 Q10 기본값대로 받아쓰기를 접고 "수동 입력만"으로 작업을 보류 처리하고 보고(팀장 결정).
- 쓰기 허용 추가: 새 마이그레이션 1개(transcribe_claimed_by 칸·claim transcribe 분기·finish transcribe 분기·만료) · `supabase/tests/*transcribe*` · `apps/worker/production/{runner,api,config}.py`·`pyproject.toml`·`uv.lock` · `apps/api/app/routes/worker_production.py` · `apps/web/src/components/production/edit/variety-*`·`variety.test.tsx` · `apps/web/src/types/db.ts`·`docs/diagrams/erd.mmd`(재생성만) · `docs/04_API.md`(A-19·W-05·W-07·W-09).
- T1 배포 안전: 워커가 W-05 요청에 지원 kind 목록(capabilities)을 보내고, claim은 transcribe를 지원한다고 알린 워커에게만 준다(옛 워커 영구 막힘 방지). 알 수 없는 kind는 워커가 거부. 롤백 절차를 구현 결정에 기록.
- T2 모델: repo·commit revision 고정, 운영자가 직접 실행하는 설치 명령(워커 CLI)으로만 받고 model.bin·tokenizer sha256 확인. 실행은 local_files_only=True, 캐시 경로는 워커 설정. 모델 없으면 즉시 transcribe_failed(자동 다운로드 금지). small·CPU(int8).
- T3 계약: transcribe는 error_stage 없이 code='transcribe_failed'(+필요 시 model_missing detail), transcript 산출물 application/json·상한 1MB. API 표(TaskKind·산출물 kind·OUTPUT_MIME·MAX_BYTES·ERROR_STAGES)와 워커 실패 경로를 kind별 분기.
- T4 상태: finish는 job status와 무관하게 transcript만 ready + transcribe_state 갱신. 승인(A-13)·상태 이탈 시 queued 받아쓰기는 failed로 정리. claim 우선순위 render > prepare > transcribe. queued 10분·running 3분 만료(렌더와 같음).
- T5 비신뢰 텍스트: vad_filter=True·no_speech 임계값, 결과는 "초안"으로 표시하고 사용자가 수정·저장해야 spec 반영. 화면 이스케이프, 로그에 대사 원문 금지.
- T6 검증: whisper 목 단위 + 로컬 DB RPC 테스트(수령·재시작·만료·상태 이탈·capabilities) + 원본→출력 컷 시각 변환 웹 테스트. 실모델 1회 실행(180초 구간 소요·최대 메모리)은 모델 설치가 운영자 명령이라 에이전트는 하지 않고, 사용자 확인 항목으로 남긴다.
