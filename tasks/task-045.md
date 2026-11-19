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

## 구현 결정 (2026-11-20, builder)
- 마이그레이션 `20261120000024_shopping_render.sql`: `claim_production_task(ws, worker, p_formats text[])` 신설(000023 본문 + `'shopping' = any(p_formats)`일 때만 쇼핑 prepare·render 새 수령), 2인자는 `'{}'`로 부르는 래퍼로 유지(구버전 워커·기존 pgTAP 호환). 권한 service_role만. pgTAP `production_shopping_render_test.sql` 9건. 테이블 변경 없음 → ERD 불변, 함수 시그니처가 늘어 `apps/web/src/types/db.ts` 재생성은 웹 금지라 하지 않음(팀장 확인).
- W-05: 선택 본문 `{capabilities: ["shopping"]}`(extra forbid, 다른 값 422). 워커는 항상 `["shopping"]`을 보낸다(R4, 해제는 워커 배포 뒤 마이그레이션 적용 순서로).
- W-06 shopping render: run 리비전 spec 참조 id(컷·BGM·narration_asset_ids) 중 이 작업·ready·render_run_id null만 서명. 컷의 source_upload는 서명하지 않고 최신 ready 파생 source를 `parent_asset_id`와 함께 준다(R5). 응답 항목에 `parent_asset_id`(그 외 null). 공용 헬퍼 `worker_production.shopping_ref_assets`를 A-15도 쓴다.
- A-15: RENDER_FORMATS에 shopping 추가, 렌더 요청 때 같은 헬퍼로 참조 자산·파생 source 재확인 → 없으면 409 field `assets`(RPC 전, fail-closed). A-16 재시도에는 넣지 않음(지시 범위: A-15).
- A-11: 쇼핑 409(field kind) 해제. **사진만 있는 쇼핑은 P0에서 준비 불가(영상 원본 ≥1, 000023 트리거·A-11 원본 확인 그대로).**
- A-09 상세 `assets[]`에 `rights`·`parent_asset_id` 추가(팀장 추가 지시, PROD-03 권리 목록).
- 검증(validation_shopping): `voice.narration_asset_id` → `voice.narration_asset_ids`(정확히 4개·중복 금지 `voice.narration_count`, 원소별 `voice.asset_invalid`). 옛 단일 필드는 스키마 오류. `disclosure.fixed`(ko "제휴 링크 포함"·ja "PR", 앞뒤 공백도 다름으로 봄). `rights.image_basis`(image만 own·licensed·ai_generated).
- 워커: `adapter_shopping.py`(spec 재검증·W-06 바인딩·문장 경계·컷 배치), `shopping/{audio,text,render}.py`, runner 형식 분기. preset `shopping-1080-v1`. lang은 ko만(ja W10).
  - 음성: 문장마다 make_hook(48k 스테레오, 앞뒤 무음 정리 — 합성 사인 기준 문장당 약 40ms 짧아짐) 실측. TTS는 4회 합계 `timeout_sec` deadline, 하나라도 실패하면 tts_failed. 녹음 누락은 audio_missing.
  - 문장 경계 = 누적 실측 길이의 30fps 반올림(R8). 음성 PCM은 이어 붙인 뒤 총 프레임×1600샘플로 자르거나 채움.
  - 컷 맞춤: 문장 안 누적 격자대로 놓고 넘치면 자르기(trimmed)·빼기(dropped), 모자라면 문장 마지막 컷 연장(extended, 영상은 tpad 정지 프레임, 사진은 표시 연장). 리포트 `cuts[].adjust`.
  - 사진(R6): 매직 바이트 jpeg·png·webp → `-f jpeg_pipe|png_pipe|webp_pipe` + protocol file, 8192px·4천만 화소 상한, 작업 해상도 2400만 화소 상한. 최대 배율 표시 크기로 한 번 디코드 후 PIL로 pan(1.1배 확대 후 ±54px 안 가로 이동, 덮임 유지)·zoom(1.0→1.1, 캔버스 중심)·none. 기본 zoom.
  - 마스크: 캔버스 좌표 가우시안 블러(반경 24). 자막(흰 글자·검정 알약, 중심 y 1380, 자동 줄바꿈 ≤3줄)·CTA(빨강 알약, 4번 문장 구간, y 1620)·표기(왼쪽 위 48,96 고정, 영상 내내). 위치·크기·블러는 가정.
  - 소리: 음성 + duck(원본 소리 0.15, 영상 컷 구간만) + BGM(0.12, -stream_loop 반복) amix → loudnorm. 음량은 가정.
  - 리포트: 문장 구간·컷 표·조정·쓴 asset_id(`assets_used`)만. 권리 목록·게시 문구는 서버(R7).
  - prepare(R1): 원본마다 하위 폴더에서 prepare 후 parent 붙여 업로드, finish meta는 첫 원본 값(가정). general도 parent를 보낸다. 쇼핑 입력 재발급은 같은 asset_id만(R2), 일반·예능형은 기존(같은 kind 최신) 유지.
- 범위 밖 발견: `app/production/shopping.py` `spec_asset_refs`가 `narration_asset_ids`를 모른다(A-10 DELETE 사전 확인). DB 트리거(000023)가 막아 409는 나지만 API 사전 확인은 빠짐 — 쓰기 허용 밖이라 미수정.

## 리뷰 반영 결정 (2026-11-20, code·security 🔴 없음)
- 1 길이 상한: 문장 음성(녹음·TTS) 1개는 make_hook 직후 ≤60초, 문장 경계 계산 뒤 총 길이 ≤180초, BGM은 `-stream_loop -1 -t 출력 길이`로 출력 길이만큼만 디코드. 넘으면 render_failed.
- 2 컷 입력 서로 다른 자산 ≤20(원본 10+사진 10, bind_inputs), render 입력 누적 다운로드 ≤2GB(가정, 파일별 상한을 남은 양으로 줄여 스트리밍 중에도 끊음). 넘으면 render_failed.
- 3 A-16 재시도도 run.revision_id로 쇼핑 참조 자산 재확인(409 field `assets`). A-15는 같은 워크스페이스에 그 Idempotency-Key run이 있으면 재확인 없이 RPC(기존 run 200), 새 run 경로에서만 재확인.
- 4 `shopping.spec_asset_refs`가 `voice.narration_asset_ids`(문자열만)를 포함 → A-10 DELETE 사전 확인 409.
- 5 `apps/web/src/types/db.ts` 재생성(`npx supabase@3.1.0 gen types typescript --local`, 3인자 claim 2줄 추가).
- 6 시각 기준(팀장 결정): 쇼핑 prepare가 job 구간(source_start_sec·segment_len_sec)을 적용하던 것을 고쳐, 원본마다 0초부터 전체(최대 60초, 넘으면 앞 60초)를 파생 source로 만든다. 컷 src 시각 = 파생 source = 원본 0초 기준(05 쇼핑 spec·04 W-06 기록). 테스트: 40초 원본 → 파생 40초, 70초 → 60초(job 구간 5/30 무시).
