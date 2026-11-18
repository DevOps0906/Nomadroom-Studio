# task-045 쇼핑 렌더러 (로컬 워커)

| 항목 | 내용 |
|---|---|
| 웨이브 | W8 |
| 선행 | task-044, task-030 |
| 위험도 | 높음 |
| 보안 영향 | 새 의존성(TTS·BGM 라이선스) · 워커 경로 보안 |
| 담당 | builder + tester |
| 근거 | `docs/research/shopping-shorts-notion-analysis.md#3`, `docs/05_DATA_MODEL.md` 쇼핑 spec, `tasks/plan-shopping-japanese.md#팀장 설계 결정` |
| 쓰기 허용 | `apps/worker/production/shopping/**`, `apps/worker/tests/production/test_shopping_render.py` |

## 할 것
- 문장별 TTS(또는 첨부 녹음) 실측 → 자막 자동 배치 → 문장 구간에 컷 길이 맞춤 → 사진 컷 pan/zoom 모션 → 마스크 블러 → 원본 소리 mute/duck·BGM → CTA·표기 → MP4·리포트(권리 목록)·게시 문구 텍스트.
- 예능형 렌더러의 캔버스·컷 파이프라인 재사용.

## 하지 않을 것
- 무음·가짜 음성 대체, 작업 폴더 밖 경로, 외부 업로드.

## 완료 조건 (실행 가능한 확인)
- [ ] `cd apps/worker && pytest -q tests/production/test_shopping_render.py` 통과(길이 = TTS ±1프레임, 마스크 영역 분산 감소)
- [ ] 산출물 ffprobe 1080×1920·30fps·h264/aac
