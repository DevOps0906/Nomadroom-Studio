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
