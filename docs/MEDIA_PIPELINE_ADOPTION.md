# 미디어 파이프라인 적용 메모 (WhisperX · HyperFrames)

작성일 2026-11-20. 상태: **제안**. 공용 기획 정본: `platform-docs:products/_platform-core/MEDIA_PIPELINE.md`. 코드·의존성은 바꾸지 않았다.

## 현황

| 항목 | 내용 | 근거 |
|---|---|---|
| STT | faster-whisper small·CPU. 보안 검사 통과 시에만, 아니면 수동 입력만 | `tasks/plan-variety-shorts.md:89` |
| 편집안 | 예능형 컷·자막 폼 | `docs/03_SCREENS_UX.md:17` |
| 렌더 | FFmpeg 중심(테스트 다수) | 코드 검색 결과 |

## 적용안

| ID | 내용 | 영향 | 선행 |
|---|---|---|---|
| N-1 | STT 단계의 단어 시각 정확도를 WhisperX로 비교해 자막 컷 경계 정밀도를 높일 수 있는지 평가 | STT 단계 | 스파이크 S1 |
| N-2 | 예능형 자막(강조 단어 색·크기)을 FFmpeg 번인과 HyperFrames 오버레이 중 어느 쪽으로 만들지 비교 | 렌더 단계 | 스파이크 S2 |

참고: 현재 STT는 CPU 소형 모델이다. WhisperX 정렬은 GPU가 있을 때 이점이 크므로 CPU 환경에서의 처리 시간이 S1의 핵심 측정값이다.

## 검증 (개발 전)

| ID | 방법 | 합격 기준(제안) |
|---|---|---|
| S1 | 예능형 영상 3편에서 CPU 처리 시간과 한국어 자막 싱크 비교 | 처리 시간이 작업 한도 안, 싱크 개선 |
| S2 | 강조 자막 1종을 두 방식으로 제작 | 결과 품질·유지 비용 비교 |
| S3 | LICENSE 원문과 `secscan` 통과 여부 | 정책 충돌 없음 |

## 하지 않을 것

| 항목 | 이유 |
|---|---|
| 보안 검사 전 STT 확대 | Q10 조건(`tasks/plan-variety-shorts.md:89`)을 유지 |

## 결정이 필요한 것

| 질문 | 선택지 | 추천(제안) |
|---|---|---|
| CPU에서 WhisperX를 허용할지 | 허용 / GPU 환경에서만 | S1의 CPU 처리 시간으로 결정 |
