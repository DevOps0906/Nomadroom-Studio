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

## 착수 결정 (2026-11-20, challenger 검토 반영 · 사용자·팀장 결정)
- 순서: task-044(000023) 커밋 뒤 착수. 새 마이그레이션 `20261120000024_shopping_render.sql`(claim 쇼핑 해제만, 000023 수정 금지).
- 사용자 결정(❓-1): TTS가 꺼져 있을 때 쇼핑 내레이션은 **문장별 녹음 4개** 업로드. spec `voice.narration_asset_ids`(정확히 4개, 문장 순서) — 문장 i의 자막 구간 = 녹음 i 실측 길이. TTS면 문장마다 생성(4회, 하나라도 실패하면 tts_failed 전체 실패, 대체·무음 금지, 4회 합계 deadline).
- 팀장 결정(❓-2·Q12): disclosure.text는 고정 문구 강제 — ko "제휴 링크 포함"(ja는 W10에서 "PR"). 검증(validation_shopping)에서 다른 값이면 오류.
- 팀장 결정(❓-3·Q13): 제휴처·숙소 제공 이미지는 쓰지 않는다. image 허용 basis는 own(직접 촬영)·licensed(라이선스 구매)·ai_generated(054 경로만). 계획서 70행과 어긋나는 문구는 Q13(사용자 결정)이 우선.
- 쓰기 허용(최종): `apps/worker/production/shopping/**` · `apps/worker/production/adapter_shopping.py` · `apps/worker/production/{runner,api,media}.py` · `apps/worker/tests/production/**`(acceptance 제외) · `apps/api/app/routes/worker_production.py`(W-06 쇼핑 입력·W-07 parent) · `apps/api/app/production/validation_shopping.py`·`tests/production/test_validation_shopping.py`(narration 4개·disclosure 고정·image basis만) · 새 마이그레이션 000024 · `supabase/tests/*shopping*` · `docs/04_API.md#W-05~#W-07` · `docs/05_DATA_MODEL.md` 쇼핑 spec.
- R1 prepare: shopping은 ready source_upload마다 prepare, W-07 항목마다 parent_asset_id(general도 맞추고 회귀).
- R2 워커 입력은 asset_id 기준 목록(같은 kind 여러 건), URL 재발급은 같은 asset_id만.
- R3 W-06 shopping render는 승인 리비전 spec이 참조하는 id 중 job·workspace 일치·ready 자산만 서명. 워커는 W-06이 주지 않은 id를 거부.
- R4 배포 안전: 워커가 지원 형식(capabilities)을 알릴 때만 쇼핑 task 배정. claim 해제는 마지막.
- R5 컷의 source_upload id는 parent로 파생 source에 매핑, 시각은 파생 source 기준. 가공 전 원본은 render에서 디코드하지 않음.
- R6 이미지: 매직 바이트 jpeg·png·webp만, `-f *_pipe` demuxer + protocol_whitelist file, MAX_DIMENSION·면적 상한. image2 패턴 확장 금지.
- R7 게시 문구는 워커가 만들지 않는다(A-21 서버). 리포트에는 쓴 asset_id만.
- R8 문장 경계는 누적 시각 반올림, 테스트는 영상·오디오 스트림 길이를 따로 ffprobe.
- 044에서 넘어온 일: A-11 쇼핑 prepare 409(field kind) 해제 + docs/04_API.md A-11 행 갱신, A-15 렌더 요청 시 승인 리비전 참조 자산 존재·ready 재확인(fail-closed), 쇼핑 preset `shopping-1080-v1`(044 결정)과 워커 상수 일치.
